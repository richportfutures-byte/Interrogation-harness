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


class ProjectionError(Exception):
    """Raised when the event log is internally inconsistent (corrupt log)."""


class LedgerProjector:
    """Folds accepted events into a canonical-ready ledger dict."""

    def project(self, events: list[dict]) -> dict:
        """Return the ledger projection for the given ordered events."""
        state = _ProjectionState()
        for event in events:
            state.apply(event)
        return state.to_ledger()


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
            ledger[ledger_key] = [
                asdict(collection[ident]) for ident in sorted(collection)
            ]
        return ledger
