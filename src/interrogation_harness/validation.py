"""Model contract validation and apply pipeline, Section 8."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.ids import IdAllocator
from interrogation_harness.model.adapter import ModelAdapter, ModelJob, ModelRequest
from interrogation_harness.model.jobs import CREATION_EVENT_TYPES, job_spec
from interrogation_harness.model.schemas import SchemaError, validate_output_schema
from interrogation_harness.projection import LedgerProjector
from interrogation_harness.provenance import apply_assumption_provenance
from interrogation_harness.records import BlastRadius
from interrogation_harness.state_machine import IllegalTransition, StateMachine

_DURABLE_REF = re.compile(r"^[ATDRCW]-\d+$")


class SemanticValidationError(Exception):
    """Raised when a parsed, schema-valid proposal cannot be applied safely."""


@dataclass(frozen=True)
class ModelValidationResult:
    """Result of one model pipeline run."""

    accepted: bool
    job: ModelJob
    raw_output: str | None = None
    parsed_output: dict[str, Any] | None = None
    events_appended: list[dict[str, Any]] = field(default_factory=list)
    ledger: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    attempts: int = 0


class ModelContractValidator:
    """Run Section 8 validation for one model job operation."""

    def __init__(
        self,
        event_log: EventLog,
        model: ModelAdapter,
        projector: LedgerProjector | None = None,
    ) -> None:
        self.event_log = event_log
        self.model = model
        self.projector = projector or LedgerProjector()

    def run(
        self,
        job: ModelJob | str,
        *,
        session_id: str,
        correlation_id: str,
        idempotency_key: str,
        timestamp: str,
        request_payload: dict[str, Any] | None = None,
        source_markdown: str = "",
        scenario: str | None = None,
    ) -> ModelValidationResult:
        """Call the model, validate its output, append accepted events, rebuild ledger."""
        resolved_job = ModelJob(job)
        if self.event_log.accepted_correlation(idempotency_key) is not None:
            ledger = self._rebuild_ledger()
            return ModelValidationResult(
                accepted=True,
                job=resolved_job,
                ledger=ledger,
                attempts=0,
            )

        payload = deepcopy(request_payload or {})
        request = ModelRequest.from_payload(resolved_job, payload)
        appended: list[dict[str, Any]] = []
        last_raw: str | None = None
        last_parsed: dict[str, Any] | None = None
        last_errors: list[str] = []
        attempts_used = 0

        for attempt in (1, 2):
            attempts_used = attempt
            try:
                raw = self.model.complete(request, scenario=scenario)
            except Exception as exc:
                event = self._append_operation_failed(
                    session_id, correlation_id, idempotency_key, timestamp, resolved_job, exc
                )
                return ModelValidationResult(
                    accepted=False,
                    job=resolved_job,
                    events_appended=[event],
                    errors=[str(exc)],
                    attempts=attempt,
                )

            last_raw = raw
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                last_errors = [f"parse error: {exc.msg}"]
                appended.append(
                    self._append_model_response(
                        session_id,
                        correlation_id,
                        idempotency_key,
                        timestamp,
                        resolved_job,
                        raw,
                        accepted=False,
                        validation_errors=last_errors,
                    )
                )
                if attempt == 1:
                    request = self._repair_request(resolved_job, payload, "parse", last_errors, raw)
                    continue
                return ModelValidationResult(
                    accepted=False,
                    job=resolved_job,
                    raw_output=last_raw,
                    events_appended=appended,
                    errors=last_errors,
                    attempts=attempt,
                )

            try:
                schema_valid = validate_output_schema(resolved_job, parsed)
            except SchemaError as exc:
                last_errors = exc.errors
                appended.append(
                    self._append_model_response(
                        session_id,
                        correlation_id,
                        idempotency_key,
                        timestamp,
                        resolved_job,
                        raw,
                        accepted=False,
                        validation_errors=last_errors,
                    )
                )
                if attempt == 1:
                    request = self._repair_request(resolved_job, payload, "schema", last_errors, raw)
                    continue
                return ModelValidationResult(
                    accepted=False,
                    job=resolved_job,
                    raw_output=last_raw,
                    parsed_output=parsed if isinstance(parsed, dict) else None,
                    events_appended=appended,
                    errors=last_errors,
                    attempts=attempt,
                )

            last_parsed = schema_valid
            break
        else:
            return ModelValidationResult(
                accepted=False,
                job=resolved_job,
                raw_output=last_raw,
                parsed_output=last_parsed,
                events_appended=appended,
                errors=last_errors,
                attempts=2,
            )

        assert last_raw is not None
        assert last_parsed is not None

        try:
            mutation_events = self._prepare_accepted_events(
                resolved_job,
                last_parsed,
                source_markdown=source_markdown,
            )
        except SemanticValidationError as exc:
            errors = [str(exc)]
            appended.append(
                self._append_model_response(
                    session_id,
                    correlation_id,
                    idempotency_key,
                    timestamp,
                    resolved_job,
                    last_raw,
                    accepted=False,
                    validation_errors=errors,
                )
            )
            appended.append(
                self.event_log.append(
                    event_type=EventType.PROPOSAL_REJECTED,
                    actor=Actor.HARNESS,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    timestamp=timestamp,
                    payload={
                        "reason": str(exc),
                        "rejected_proposal": last_parsed,
                    },
                )
            )
            return ModelValidationResult(
                accepted=False,
                job=resolved_job,
                raw_output=last_raw,
                parsed_output=last_parsed,
                events_appended=appended,
                errors=errors,
                attempts=attempts_used,
            )

        appended.append(
            self._append_model_response(
                session_id,
                correlation_id,
                idempotency_key,
                timestamp,
                resolved_job,
                last_raw,
                accepted=True,
                validation_errors=[],
            )
        )
        for prepared in mutation_events:
            appended.append(
                self.event_log.append(
                    event_type=prepared["event_type"],
                    actor=prepared.get("actor", Actor.HARNESS),
                    session_id=session_id,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    timestamp=timestamp,
                    payload=prepared.get("payload", {}),
                    ref_map=prepared.get("ref_map"),
                )
            )
        ledger = self._rebuild_ledger()
        return ModelValidationResult(
            accepted=True,
            job=resolved_job,
            raw_output=last_raw,
            parsed_output=last_parsed,
            events_appended=appended,
            ledger=ledger,
            attempts=attempts_used,
        )

    def _prepare_accepted_events(
        self,
        job: ModelJob,
        parsed: dict[str, Any],
        *,
        source_markdown: str,
    ) -> list[dict[str, Any]]:
        spec = job_spec(job)
        ledger = self.projector.project(self.event_log.read_events())
        refs = _ProjectionRefs(ledger)
        if job == ModelJob.INITIAL_EXTRACTION:
            return self._prepare_initial_extraction(parsed, refs, source_markdown)
        if job == ModelJob.RANK_NEXT_WORK_ITEM:
            self._semantic_rank_next(parsed, refs)
            return []
        if job == ModelJob.INTERPRET_USER_ANSWER:
            return self._prepare_interpret_events(parsed, refs, source_markdown)
        if job == ModelJob.CONTRADICTION_AUDIT:
            self._semantic_audit(parsed, refs)
            return [
                {
                    "event_type": spec.records_event_type,
                    "payload": {"findings_summary": parsed},
                }
            ]
        if job == ModelJob.ARTIFACT_GENERATION:
            self._semantic_artifact(parsed, refs)
            return [
                {
                    "event_type": spec.records_event_type,
                    "payload": parsed,
                }
            ]
        raise SemanticValidationError(f"unsupported job: {job.value}")

    def _prepare_initial_extraction(
        self,
        parsed: dict[str, Any],
        refs: "_ProjectionRefs",
        source_markdown: str,
    ) -> list[dict[str, Any]]:
        temp_handles = _collect_initial_temp_handles(parsed)
        ref_map = IdAllocator.from_ledger(refs.ledger).allocate(temp_handles)
        temp_refs = set(ref_map)
        events: list[dict[str, Any]] = []

        for assumption in parsed["assumptions"]:
            payload = _without_keys(assumption, {"tmp_handle", "external_fact"})
            payload = apply_assumption_provenance(payload, source_markdown)
            payload["id"] = ref_map[assumption["tmp_handle"]]
            events.append(_prepared(EventType.ASSUMPTION_CREATED, payload, assumption["tmp_handle"], ref_map))

        for term in parsed["terms"]:
            payload = _without_keys(term, {"tmp_handle"})
            payload["id"] = ref_map[term["tmp_handle"]]
            events.append(_prepared(EventType.TERM_CREATED, payload, term["tmp_handle"], ref_map))

        for decision in parsed["decisions"]:
            payload = _without_keys(decision, {"tmp_handle"})
            payload["id"] = ref_map[decision["tmp_handle"]]
            events.append(_prepared(EventType.DECISION_CREATED, payload, decision["tmp_handle"], ref_map))

        for risk in parsed["risks"]:
            payload = _without_keys(risk, {"tmp_handle"})
            payload["id"] = ref_map[risk["tmp_handle"]]
            payload["source_refs"] = [
                _resolve_creation_ref(value, refs, ref_map, temp_refs)
                for value in risk.get("source_refs", [])
            ]
            events.append(_prepared(EventType.RISK_CREATED, payload, risk["tmp_handle"], ref_map))

        for contradiction in parsed["contradictions"]:
            payload = _without_keys(contradiction, {"tmp_handle"})
            payload["id"] = ref_map[contradiction["tmp_handle"]]
            payload["refs"] = [
                _resolve_creation_ref(value, refs, ref_map, temp_refs)
                for value in contradiction.get("refs", [])
            ]
            events.append(
                _prepared(EventType.CONTRADICTION_CREATED, payload, contradiction["tmp_handle"], ref_map)
            )

        for work_item in parsed["work_items"]:
            if work_item.get("blast_radius") == BlastRadius.HIGH.value and not work_item.get("blocks_closure"):
                raise SemanticValidationError("high blast radius work items must block closure")
            related = work_item.get("related_temp_refs", [])
            target_entity = None
            if related:
                target_entity = _resolve_creation_ref(related[0], refs, ref_map, temp_refs)
            payload = _without_keys(work_item, {"tmp_handle", "related_temp_refs"})
            payload["id"] = ref_map[work_item["tmp_handle"]]
            payload["target_entity"] = target_entity
            events.append(_prepared(EventType.WORK_ITEM_CREATED, payload, work_item["tmp_handle"], ref_map))

        return events

    def _semantic_rank_next(self, parsed: dict[str, Any], refs: "_ProjectionRefs") -> None:
        selected = parsed["selected_work_item_id"]
        work_item = refs.get(selected)
        if work_item is None or not refs.is_work_item(selected):
            raise SemanticValidationError(f"selected work item does not exist: {selected!r}")
        if work_item.get("status") == "resolved":
            raise SemanticValidationError(f"selected work item is resolved: {selected!r}")
        tested = parsed.get("tested_entity_id")
        if tested is not None and not refs.exists(tested):
            raise SemanticValidationError(f"tested entity does not exist: {tested!r}")
        _check_recommended_default(parsed, refs)

    def _prepare_interpret_events(
        self,
        parsed: dict[str, Any],
        refs: "_ProjectionRefs",
        source_markdown: str,
    ) -> list[dict[str, Any]]:
        proposed = parsed["proposed_events"]
        self._semantic_interpret(proposed, refs)
        handles = [
            event["payload"]["tmp_handle"]
            for event in proposed
            if event["event_type"] in CREATION_EVENT_TYPES
        ]
        ref_map = IdAllocator.from_ledger(refs.ledger).allocate(handles)
        temp_refs = set(ref_map)
        events: list[dict[str, Any]] = []
        for item in proposed:
            event_type = EventType(item["event_type"])
            if item["event_type"] in CREATION_EVENT_TYPES:
                payload = self._creation_payload_from_event(
                    event_type, item["payload"], refs, ref_map, temp_refs, source_markdown
                )
                events.append(_prepared(event_type, payload, item["payload"]["tmp_handle"], ref_map))
            else:
                payload = deepcopy(item["payload"])
                payload["id"] = item["target_ref"]
                events.append({"event_type": event_type, "payload": payload})
        return events

    def _semantic_interpret(
        self, proposed_events: list[dict[str, Any]], refs: "_ProjectionRefs"
    ) -> None:
        statuses = refs.status_map()
        for item in proposed_events:
            event_type = item["event_type"]
            if event_type in CREATION_EVENT_TYPES:
                self._semantic_creation_refs(item["payload"], refs)
                continue
            target = item["target_ref"]
            if not refs.exists(target):
                raise SemanticValidationError(f"target reference does not exist: {target!r}")
            entity_type = _entity_type_for_transition(event_type)
            if not refs.matches_entity_type(target, entity_type):
                raise SemanticValidationError(
                    f"{event_type} target has wrong entity type: {target!r}"
                )
            payload = item["payload"]
            current = statuses.get(target)
            if payload.get("from") != current:
                raise SemanticValidationError(
                    f"{target} transition from mismatch: {payload.get('from')!r} != {current!r}"
                )
            try:
                StateMachine.check(entity_type, payload["from"], payload["to"])
            except IllegalTransition as exc:
                raise SemanticValidationError(str(exc)) from exc
            statuses[target] = payload["to"]
            basis = payload.get("recommended_default_basis")
            if basis is not None and not refs.exists(basis):
                raise SemanticValidationError(
                    f"recommended default basis does not exist: {basis!r}"
                )
            resolution_work_item = payload.get("resolution_work_item")
            if resolution_work_item is not None and not refs.exists(resolution_work_item):
                raise SemanticValidationError(
                    f"resolution work item does not exist: {resolution_work_item!r}"
                )

    def _semantic_creation_refs(self, payload: dict[str, Any], refs: "_ProjectionRefs") -> None:
        for value in _walk_values(payload):
            if IdAllocator.is_durable_id(value) and not refs.exists(value):
                raise SemanticValidationError(f"durable reference does not exist: {value!r}")
        if payload.get("recommended_default") is not None:
            basis = payload.get("recommended_default_basis")
            if basis is None or not refs.exists(basis):
                raise SemanticValidationError(
                    f"recommended default basis does not exist: {basis!r}"
                )

    def _creation_payload_from_event(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        refs: "_ProjectionRefs",
        ref_map: dict[str, str],
        temp_refs: set[str],
        source_markdown: str,
    ) -> dict[str, Any]:
        out = _without_keys(payload, {"tmp_handle", "related_temp_refs", "external_fact"})
        out["id"] = ref_map[payload["tmp_handle"]]
        if event_type == EventType.ASSUMPTION_CREATED:
            out = apply_assumption_provenance(out, source_markdown)
        if event_type == EventType.RISK_CREATED:
            out["source_refs"] = [
                _resolve_creation_ref(value, refs, ref_map, temp_refs)
                for value in payload.get("source_refs", [])
            ]
        if event_type == EventType.CONTRADICTION_CREATED:
            out["refs"] = [
                _resolve_creation_ref(value, refs, ref_map, temp_refs)
                for value in payload.get("refs", [])
            ]
        if event_type == EventType.WORK_ITEM_CREATED:
            related = payload.get("related_temp_refs", [])
            if related:
                out["target_entity"] = _resolve_creation_ref(related[0], refs, ref_map, temp_refs)
        return out

    def _semantic_audit(self, parsed: dict[str, Any], refs: "_ProjectionRefs") -> None:
        for finding in parsed.get("findings", []):
            for ref in finding.get("refs", []):
                if not refs.exists(ref):
                    raise SemanticValidationError(f"audit reference does not exist: {ref!r}")
        for key in ("missing_provenance", "invalid_source_excerpts", "unresolved_high_blast_radius"):
            for ref in parsed.get(key, []):
                if IdAllocator.is_durable_id(ref) and not refs.exists(ref):
                    raise SemanticValidationError(f"audit reference does not exist: {ref!r}")
        for blocker in parsed.get("artifact_blockers", []):
            for value in _walk_values(blocker):
                if IdAllocator.is_durable_id(value) and not refs.exists(value):
                    raise SemanticValidationError(f"audit blocker reference does not exist: {value!r}")

    def _semantic_artifact(self, parsed: dict[str, Any], refs: "_ProjectionRefs") -> None:
        for item in parsed.get("traceability_summary", []):
            if isinstance(item, dict):
                entity_id = item.get("entity_id")
                if entity_id is not None and not refs.exists(entity_id):
                    raise SemanticValidationError(
                        f"traceability entity does not exist: {entity_id!r}"
                    )
        for risk in parsed.get("open_risk_register", []):
            if isinstance(risk, dict):
                risk_id = risk.get("id")
                if IdAllocator.is_durable_id(risk_id) and not refs.exists(risk_id):
                    raise SemanticValidationError(f"risk does not exist: {risk_id!r}")
        locked_bullets = _locked_assumption_bullets(parsed.get("artifact_markdown", ""))
        locked_statements = {
            item["statement"]
            for item in refs.ledger.get("assumptions", [])
            if item.get("status") == "locked"
        }
        for bullet in locked_bullets:
            if not any(statement in bullet for statement in locked_statements):
                raise SemanticValidationError(
                    f"artifact invents locked assumption: {bullet!r}"
                )

    def _append_operation_failed(
        self,
        session_id: str,
        correlation_id: str,
        idempotency_key: str,
        timestamp: str,
        job: ModelJob,
        exc: Exception,
    ) -> dict[str, Any]:
        return self.event_log.append(
            event_type=EventType.OPERATION_FAILED,
            actor=Actor.HARNESS,
            session_id=session_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            timestamp=timestamp,
            payload={
                "job": job.value,
                "retryable": True,
                "error": str(exc),
            },
        )

    def _append_model_response(
        self,
        session_id: str,
        correlation_id: str,
        idempotency_key: str,
        timestamp: str,
        job: ModelJob,
        raw_output: str,
        *,
        accepted: bool,
        validation_errors: list[str],
    ) -> dict[str, Any]:
        return self.event_log.append(
            event_type=EventType.MODEL_RESPONSE_RECORDED,
            actor=Actor.MODEL,
            session_id=session_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            timestamp=timestamp,
            payload={
                "job": job.value,
                "raw_output": raw_output,
                "accepted": accepted,
                "validation_errors": validation_errors,
            },
        )

    def _repair_request(
        self,
        job: ModelJob,
        original_payload: dict[str, Any],
        stage: str,
        errors: list[str],
        raw_output: str,
    ) -> ModelRequest:
        payload = deepcopy(original_payload)
        payload["repair"] = {
            "stage": stage,
            "errors": errors,
            "raw_output": raw_output,
        }
        return ModelRequest.from_payload(job, payload)

    def _rebuild_ledger(self) -> dict[str, Any]:
        ledger = self.projector.project(self.event_log.read_events())
        self.event_log.store.write_ledger(ledger)
        return ledger


class _ProjectionRefs:
    """Convenience lookups over a projected ledger."""

    def __init__(self, ledger: dict[str, Any]) -> None:
        self.ledger = ledger
        self._items: dict[str, dict[str, Any]] = {}
        self._types: dict[str, str] = {}
        for key, entity_type in (
            ("assumptions", "assumption"),
            ("terms", "term"),
            ("decisions", "decision"),
            ("risks", "risk"),
            ("contradictions", "contradiction"),
            ("work_items", "work_item"),
        ):
            for item in ledger.get(key, []):
                ident = item.get("id")
                if isinstance(ident, str):
                    self._items[ident] = item
                    self._types[ident] = entity_type

    def exists(self, ref: Any) -> bool:
        return isinstance(ref, str) and ref in self._items

    def get(self, ref: str) -> dict[str, Any] | None:
        return self._items.get(ref)

    def is_work_item(self, ref: str) -> bool:
        return self._types.get(ref) == "work_item"

    def matches_entity_type(self, ref: str, entity_type: str) -> bool:
        return self._types.get(ref) == entity_type

    def status_map(self) -> dict[str, str]:
        return {
            ident: item["status"]
            for ident, item in self._items.items()
            if "status" in item
        }


def _prepared(
    event_type: EventType,
    payload: dict[str, Any],
    handle: str,
    ref_map: dict[str, str],
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "payload": payload,
        "ref_map": {handle: ref_map[handle]},
    }


def _without_keys(item: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in item.items() if key not in keys}


def _collect_initial_temp_handles(parsed: dict[str, Any]) -> list[str]:
    handles: list[str] = []
    for key in ("assumptions", "terms", "decisions", "risks", "contradictions", "work_items"):
        handles.extend(item["tmp_handle"] for item in parsed.get(key, []))
    return handles


def _resolve_creation_ref(
    value: str,
    refs: _ProjectionRefs,
    ref_map: dict[str, str],
    temp_refs: set[str],
) -> str:
    if value in temp_refs:
        return ref_map[value]
    if refs.exists(value):
        return value
    raise SemanticValidationError(f"reference does not exist: {value!r}")


def _check_recommended_default(parsed: dict[str, Any], refs: _ProjectionRefs) -> None:
    if parsed.get("recommended_default") is None:
        return
    basis = parsed.get("recommended_default_basis")
    if basis is None or not refs.exists(basis):
        raise SemanticValidationError(
            f"recommended default basis does not exist: {basis!r}"
        )


def _entity_type_for_transition(event_type: str) -> str:
    return {
        EventType.ASSUMPTION_TRANSITIONED.value: "assumption",
        EventType.TERM_TRANSITIONED.value: "term",
        EventType.DECISION_TRANSITIONED.value: "decision",
        EventType.RISK_TRANSITIONED.value: "risk",
        EventType.CONTRADICTION_TRANSITIONED.value: "contradiction",
        EventType.WORK_ITEM_STATUS_CHANGED.value: "work_item",
    }[event_type]


def _walk_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


def _locked_assumption_bullets(markdown: str) -> list[str]:
    bullets: list[str] = []
    in_section = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower() == "## locked assumptions"
            continue
        if in_section and stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets
