"""LedgerProjector: a pure fold over accepted events into the ledger (Sections 2, 4).

Invariants enforced here:
  - Pure and side-effect free: no model call, no clock, no identity minting, no read of
    anything outside the events passed in. Durable IDs are read from events only.
  - The event log is the sole authority: the projector always derives the ledger from
    events, so any prior ledger.json is irrelevant and disposable.
  - Only accepted state-mutating events change projection state. MODEL_RESPONSE_RECORDED
    (accepted true or false), OPERATION_FAILED, and PROPOSAL_REJECTED never mutate.
  - At most one work item may be active (Section 4.2).

Entity records come from :mod:`interrogation_harness.records`. Status values are stored
as their string form, which is what the canonical ledger requires. Transitions are
checked against the Section 10 tables via :class:`StateMachine` as a defensive guard; an
event log carrying an illegal transition is corrupt and the fold raises.
"""

from __future__ import annotations

from dataclasses import asdict

from .records import (
    Assumption,
    Contradiction,
    Decision,
    EvidenceStatus,
    GapType,
    PremiseOrigin,
    Risk,
    RevisionEntry,
    Term,
    WorkItem,
)
from .state_machine import StateMachine

# Recorded but non state-mutating event types (Section 6.2).
_NO_OP_EVENTS = frozenset(
    {
        "MODEL_RESPONSE_RECORDED",
        "OPERATION_FAILED",
        "PROPOSAL_REJECTED",
        "AUDIT_RUN",
        "ARTIFACT_GENERATED",
    }
)

_LEDGER_ARRAYS = (
    ("assumptions", "_assumptions"),
    ("terms", "_terms"),
    ("decisions", "_decisions"),
    ("risks", "_risks"),
    ("contradictions", "_contradictions"),
    ("work_items", "_work_items"),
)

# V2 signal constants (V2 Implementation Spec, Sections 2.2 and 5). These job and
# audit-type names are read as structured, harness-written event fields. V2 model jobs
# and the blind-spot audit are not implemented yet (later stages), so in V1 sessions
# these signals are simply absent and the V2 ledger fields are not emitted.
_V2_INTAKE_JOB = "intake_unstructured_input"
_BLIND_SPOT_AUDIT_TYPE = "blind_spot"
_CREATION_EVENT_TYPES = frozenset(
    {
        "ASSUMPTION_CREATED",
        "TERM_CREATED",
        "DECISION_CREATED",
        "RISK_CREATED",
        "CONTRADICTION_CREATED",
        "WORK_ITEM_CREATED",
    }
)
_SESSION_FRAME_FIELDS = ("topic", "downstream_use", "closure_standard", "input_mode")

# V2 optional entity fields, omitted from the projected record when null or empty
# (Section 2.4). Mapped per ledger array so V1 arrays are untouched.
_ASSUMPTION_V2_FIELDS = ("intake_label", "premise_origin", "evidence_status", "depends_on")
_WORK_ITEM_V2_FIELDS = (
    "derived_question_label",
    "gap_type",
    "source_assumption_ids",
    "blocking_reason",
)
_V2_FIELDS_BY_ARRAY = {
    "assumptions": _ASSUMPTION_V2_FIELDS,
    "work_items": _WORK_ITEM_V2_FIELDS,
}


class ProjectionError(Exception):
    """Raised when the event log is internally inconsistent (corrupt log)."""


def _validate_v2_enum(value, enum_cls, field_name: str):
    """Return value if it is a legal enum member value or None; else raise.

    Simple enum support for V2 creation events. Full V2 creation validation lives in
    the validator (a later stage); this guard keeps the projection honest.
    """
    if value is None:
        return None
    legal = {member.value for member in enum_cls}
    if value not in legal:
        raise ProjectionError(f"invalid {field_name}: {value!r}")
    return value


def _omit_empty_v2_fields(record: dict, fields: tuple[str, ...]) -> dict:
    """Drop V2 fields from a serialized record when null or empty (Section 2.4)."""
    for name in fields:
        value = record.get(name)
        if value is None or (isinstance(value, list) and not value):
            record.pop(name, None)
    return record


class LedgerProjector:
    """Folds accepted events into a canonical-ready ledger dict."""

    def project(self, events: list[dict]) -> dict:
        """Return the ledger projection for the given ordered events.

        The V1 entity fold is unchanged. V2 ledger fields are derived in a separate
        pure pass and attached only when the session is V2 (Decision D3, Section 2.5),
        so a V1 session serializes byte-for-byte as before.
        """
        state = _ProjectionState()
        for event in events:
            state.apply(event)
        ledger = state.to_ledger()
        v2_fields = _project_v2_fields(events)
        if v2_fields is not None:
            ledger.update(v2_fields)
        return ledger


class _ProjectionState:
    """Mutable accumulator used within a single fold."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.schema_version: str | None = None
        self.source_hash: str | None = None
        self.force_closed: bool = False
        self.force_closed_event: str | None = None
        self._assumptions: dict[str, Assumption] = {}
        self._terms: dict[str, Term] = {}
        self._decisions: dict[str, Decision] = {}
        self._risks: dict[str, Risk] = {}
        self._contradictions: dict[str, Contradiction] = {}
        self._work_items: dict[str, WorkItem] = {}

    # -- dispatch ----------------------------------------------------------

    def apply(self, event: dict) -> None:
        event_type = event.get("event_type")
        if event_type in _NO_OP_EVENTS:
            return
        handler = getattr(self, f"_on_{event_type}", None)
        if handler is None:
            raise ProjectionError(f"unknown event type in log: {event_type!r}")
        handler(event)

    # -- session and lifecycle --------------------------------------------

    def _on_SESSION_CREATED(self, event: dict) -> None:
        payload = event.get("payload", {})
        self.session_id = payload.get("session_id", event.get("session_id"))
        self.schema_version = event.get("schema_version")

    def _on_SOURCE_ADDED(self, event: dict) -> None:
        self.source_hash = event.get("payload", {}).get("content_hash", self.source_hash)

    def _on_FORCE_CLOSED(self, event: dict) -> None:
        self.force_closed = True
        self.force_closed_event = event["event_id"]

    # -- creations ---------------------------------------------------------

    def _on_ASSUMPTION_CREATED(self, event: dict) -> None:
        p = event["payload"]
        eid = event["event_id"]
        self._require_new(self._assumptions, p["id"], eid)
        self._assumptions[p["id"]] = Assumption(
            id=p["id"],
            statement=p["statement"],
            status=p.get("status", "candidate"),
            source_type=p["source_type"],
            blast_radius=p["blast_radius"],
            downstream_impact=p.get("downstream_impact", ""),
            risk_if_wrong=p.get("risk_if_wrong", ""),
            created_event=eid,
            updated_event=eid,
            source_excerpt=p.get("source_excerpt"),
            source_excerpt_verified=bool(p.get("source_excerpt_verified", False)),
            tested_by_work_item=p.get("tested_by_work_item"),
            user_answer_events=list(p.get("user_answer_events", [])),
            revision_history=[
                RevisionEntry(**entry) for entry in p.get("revision_history", [])
            ],
            intake_label=p.get("intake_label"),
            premise_origin=_validate_v2_enum(
                p.get("premise_origin"), PremiseOrigin, "premise_origin"
            ),
            evidence_status=_validate_v2_enum(
                p.get("evidence_status"), EvidenceStatus, "evidence_status"
            ),
            depends_on=list(p.get("depends_on", [])),
        )

    def _on_TERM_CREATED(self, event: dict) -> None:
        p = event["payload"]
        eid = event["event_id"]
        self._require_new(self._terms, p["id"], eid)
        self._terms[p["id"]] = Term(
            id=p["id"],
            term=p["term"],
            status=p.get("status", "undefined"),
            created_event=eid,
            updated_event=eid,
            definition=p.get("definition"),
            revision_history=[
                RevisionEntry(**entry) for entry in p.get("revision_history", [])
            ],
        )

    def _on_DECISION_CREATED(self, event: dict) -> None:
        p = event["payload"]
        eid = event["event_id"]
        self._require_new(self._decisions, p["id"], eid)
        self._decisions[p["id"]] = Decision(
            id=p["id"],
            decision=p["decision"],
            status=p.get("status", "needed"),
            created_event=eid,
            updated_event=eid,
            rationale=p.get("rationale"),
            revision_history=[
                RevisionEntry(**entry) for entry in p.get("revision_history", [])
            ],
        )

    def _on_RISK_CREATED(self, event: dict) -> None:
        p = event["payload"]
        eid = event["event_id"]
        self._require_new(self._risks, p["id"], eid)
        self._risks[p["id"]] = Risk(
            id=p["id"],
            statement=p["statement"],
            severity=p["severity"],
            status=p.get("status", "open"),
            created_event=eid,
            updated_event=eid,
            source_refs=list(p.get("source_refs", [])),
        )

    def _on_CONTRADICTION_CREATED(self, event: dict) -> None:
        p = event["payload"]
        eid = event["event_id"]
        self._require_new(self._contradictions, p["id"], eid)
        self._contradictions[p["id"]] = Contradiction(
            id=p["id"],
            refs=list(p["refs"]),
            severity=p["severity"],
            description=p.get("description", ""),
            status=p.get("status", "open"),
            created_event=eid,
            updated_event=eid,
            resolution_work_item=p.get("resolution_work_item"),
        )

    def _on_WORK_ITEM_CREATED(self, event: dict) -> None:
        p = event["payload"]
        eid = event["event_id"]
        self._require_new(self._work_items, p["id"], eid)
        self._work_items[p["id"]] = WorkItem(
            id=p["id"],
            kind=p["kind"],
            status=p.get("status", "open"),
            question=p.get("question", ""),
            why_it_matters=p.get("why_it_matters", ""),
            what_breaks_if_wrong=p.get("what_breaks_if_wrong", ""),
            blast_radius=p["blast_radius"],
            blocks_closure=bool(p.get("blocks_closure", False)),
            created_event=eid,
            updated_event=eid,
            target_entity=p.get("target_entity"),
            recommended_default=p.get("recommended_default"),
            recommended_default_basis=p.get("recommended_default_basis"),
            answer_options=list(p.get("answer_options", [])),
            deferred_reason=p.get("deferred_reason"),
            derived_question_label=p.get("derived_question_label"),
            gap_type=_validate_v2_enum(p.get("gap_type"), GapType, "gap_type"),
            source_assumption_ids=list(p.get("source_assumption_ids", [])),
            blocking_reason=p.get("blocking_reason"),
        )
        self._check_single_active()

    # -- transitions -------------------------------------------------------

    def _on_ASSUMPTION_TRANSITIONED(self, event: dict) -> None:
        entity = self._transition(self._assumptions, "assumption", event)
        p = event["payload"]
        if p.get("to") == "revised":
            entity.revision_history.append(
                RevisionEntry(
                    event_id=event["event_id"],
                    prior_statement=p["prior_statement"],
                    new_statement=p["new_statement"],
                )
            )
            entity.statement = p["new_statement"]
        user_answer_event = p.get("user_answer_event")
        if user_answer_event:
            entity.user_answer_events.append(user_answer_event)

    def _on_TERM_TRANSITIONED(self, event: dict) -> None:
        entity = self._transition(self._terms, "term", event)
        p = event["payload"]
        if p.get("to") == "revised":
            entity.revision_history.append(
                RevisionEntry(
                    event_id=event["event_id"],
                    prior_statement=p["prior_statement"],
                    new_statement=p["new_statement"],
                )
            )
            entity.definition = p["new_statement"]

    def _on_DECISION_TRANSITIONED(self, event: dict) -> None:
        entity = self._transition(self._decisions, "decision", event)
        p = event["payload"]
        if p.get("to") == "revised":
            entity.revision_history.append(
                RevisionEntry(
                    event_id=event["event_id"],
                    prior_statement=p["prior_statement"],
                    new_statement=p["new_statement"],
                )
            )
            entity.decision = p["new_statement"]

    def _on_RISK_TRANSITIONED(self, event: dict) -> None:
        self._transition(self._risks, "risk", event)

    def _on_CONTRADICTION_TRANSITIONED(self, event: dict) -> None:
        entity = self._transition(self._contradictions, "contradiction", event)
        p = event["payload"]
        if "resolution_work_item" in p:
            entity.resolution_work_item = p["resolution_work_item"]

    def _on_WORK_ITEM_STATUS_CHANGED(self, event: dict) -> None:
        entity = self._transition(self._work_items, "work_item", event)
        p = event["payload"]
        if "deferred_reason" in p:
            entity.deferred_reason = p["deferred_reason"]
        self._check_single_active()

    def _on_QUESTION_ASKED(self, event: dict) -> None:
        p = event["payload"]
        work_item_id = p["work_item_id"]
        entity = self._work_items.get(work_item_id)
        if entity is None:
            raise ProjectionError(
                f"QUESTION_ASKED targets missing work item: {work_item_id!r}"
            )
        snapshot = p.get("question_snapshot", {})
        for field in (
            "question",
            "why_it_matters",
            "what_breaks_if_wrong",
            "recommended_default",
            "recommended_default_basis",
        ):
            if field in snapshot:
                setattr(entity, field, snapshot[field])
        if "answer_options" in snapshot:
            entity.answer_options = list(snapshot["answer_options"])
        entity.updated_event = event["event_id"]

    # -- helpers -----------------------------------------------------------

    def _transition(self, collection: dict, entity_type: str, event: dict):
        p = event["payload"]
        ident = p["id"]
        entity = collection.get(ident)
        if entity is None:
            raise ProjectionError(
                f"transition targets missing {entity_type}: {ident!r}"
            )
        current = entity.status
        declared_from = p.get("from")
        if declared_from is not None and declared_from != current:
            raise ProjectionError(
                f"{entity_type} {ident} from mismatch: event says {declared_from!r}, "
                f"state is {current!r}"
            )
        target = p["to"]
        StateMachine.check(entity_type, current, target)
        entity.status = target
        entity.updated_event = event["event_id"]
        return entity

    def _check_single_active(self) -> None:
        active = [w.id for w in self._work_items.values() if w.status == "active"]
        if len(active) > 1:
            raise ProjectionError(
                f"more than one active work item: {sorted(active)}"
            )

    @staticmethod
    def _require_new(collection: dict, ident: str, event_id: str) -> None:
        if ident in collection:
            raise ProjectionError(
                f"duplicate entity id in log: {ident!r} (event {event_id})"
            )

    # -- output ------------------------------------------------------------

    def to_ledger(self) -> dict:
        ledger: dict = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "source_hash": self.source_hash,
            "force_closed": self.force_closed,
            "force_closed_event": self.force_closed_event,
        }
        for ledger_key, attr in _LEDGER_ARRAYS:
            collection = getattr(self, attr)
            v2_fields = _V2_FIELDS_BY_ARRAY.get(ledger_key, ())
            ledger[ledger_key] = [
                _omit_empty_v2_fields(asdict(collection[ident]), v2_fields)
                for ident in sorted(collection)
            ]
        return ledger


# ---------------------------------------------------------------------------
# V2 ledger field projection (V2 Implementation Spec, Section 2.2)
#
# These functions are a pure second pass over the same events. They never call the
# model, read a clock, mint identity, or parse raw_output. They read only structured,
# harness-written payload fields.
# ---------------------------------------------------------------------------


def _is_accepted_intake_response(event: dict) -> bool:
    if event.get("event_type") != "MODEL_RESPONSE_RECORDED":
        return False
    payload = event.get("payload", {})
    return payload.get("job") == _V2_INTAKE_JOB and payload.get("accepted") is True


def _is_blind_spot_audit(event: dict) -> bool:
    return (
        event.get("event_type") == "AUDIT_RUN"
        and event.get("payload", {}).get("audit_type") == _BLIND_SPOT_AUDIT_TYPE
    )


def _project_protocol_version(events: list[dict]) -> str:
    version = "1.0.0"
    for event in events:
        if event.get("event_type") == "SESSION_CREATED":
            declared = event.get("payload", {}).get("protocol_version")
            if declared is not None:
                version = declared
    # Inference only ever upgrades to 2.0.0; it never downgrades an explicit 2.0.0.
    for event in events:
        if _is_accepted_intake_response(event) or _is_blind_spot_audit(event):
            return "2.0.0"
    return version


def _project_session_frame(events: list[dict]) -> dict:
    frame = {field: None for field in _SESSION_FRAME_FIELDS}
    session_created_frame: dict | None = None
    intake_frame: dict | None = None
    for event in events:
        if event.get("event_type") == "SESSION_CREATED":
            candidate = event.get("payload", {}).get("session_frame")
            if isinstance(candidate, dict) and session_created_frame is None:
                session_created_frame = candidate
        elif _is_accepted_intake_response(event):
            candidate = event.get("payload", {}).get("session_frame")
            if isinstance(candidate, dict) and intake_frame is None:
                intake_frame = candidate
    chosen = session_created_frame if session_created_frame is not None else intake_frame
    if chosen is not None:
        for field in _SESSION_FRAME_FIELDS:
            frame[field] = chosen.get(field)
    return frame


def _project_intake_status(events: list[dict], protocol_version: str) -> str:
    if protocol_version != "2.0.0":
        return "not_required"
    has_source = any(event.get("event_type") == "SOURCE_ADDED" for event in events)
    if not has_source:
        return "not_required"
    accepted_intake_correlations = {
        event.get("correlation_id")
        for event in events
        if _is_accepted_intake_response(event)
    }
    if not accepted_intake_correlations:
        return "required"
    creation_correlations = {
        event.get("correlation_id")
        for event in events
        if event.get("event_type") in _CREATION_EVENT_TYPES
    }
    if accepted_intake_correlations & creation_correlations:
        return "complete"
    return "required"


def _project_blind_spot_status(events: list[dict]) -> str:
    for event in events:
        if _is_blind_spot_audit(event):
            return "complete"
    return "not_run"


def _project_v2_fields(events: list[dict]) -> dict | None:
    """Return the four V2 ledger fields, or None when the session is V1."""
    protocol_version = _project_protocol_version(events)
    if protocol_version != "2.0.0":
        return None
    return {
        "protocol_version": protocol_version,
        "session_frame": _project_session_frame(events),
        "intake_status": _project_intake_status(events, protocol_version),
        "blind_spot_audit_status": _project_blind_spot_status(events),
    }
