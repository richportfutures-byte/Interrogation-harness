"""Explicit model output schema validators, no runtime dependencies."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

from interrogation_harness.events import EventType
from interrogation_harness.ids import IdAllocator
from interrogation_harness.model.adapter import ModelJob
from interrogation_harness.model.jobs import CREATION_EVENT_TYPES, INTERPRET_ALLOWED_EVENT_TYPES
from interrogation_harness.records import (
    AnswerClass,
    AssumptionStatus,
    BlastRadius,
    ContradictionStatus,
    DecisionStatus,
    EvidenceStatus,
    GapType,
    RiskStatus,
    Severity,
    SourceType,
    TermStatus,
    WorkItemKind,
)

_CA_LABEL = re.compile(r"^CA-\d{2,}$")
_DQ_LABEL = re.compile(r"^DQ-\d{2,}$")
_INPUT_MODES = {"structured", "unstructured", "mixed"}
_SESSION_FRAME_FIELDS = {"topic", "downstream_use", "closure_standard", "input_mode"}


class SchemaError(Exception):
    """Raised when raw model JSON violates a job output schema."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


_INITIAL_TOP = {
    "assumptions",
    "work_items",
    "risks",
    "terms",
    "decisions",
    "contradictions",
}
_ASSUMPTION_FIELDS = {
    "tmp_handle",
    "statement",
    "status",
    "source_type",
    "source_excerpt",
    "blast_radius",
    "downstream_impact",
    "risk_if_wrong",
    "external_fact",
}
_WORK_ITEM_FIELDS = {
    "tmp_handle",
    "kind",
    "question",
    "why_it_matters",
    "what_breaks_if_wrong",
    "blast_radius",
    "blocks_closure",
    "related_temp_refs",
    "answer_options",
    "recommended_default",
    "recommended_default_basis",
}
_RISK_FIELDS = {"tmp_handle", "statement", "severity", "status", "source_refs"}
_TERM_FIELDS = {"tmp_handle", "term", "definition", "status"}
_DECISION_FIELDS = {"tmp_handle", "decision", "rationale", "status"}
_CONTRADICTION_FIELDS = {
    "tmp_handle",
    "refs",
    "severity",
    "description",
    "status",
}

# V2 intake field sets (V2 spec Section 4.1).
_INTAKE_TOP = {
    "session_frame",
    "assumptions",
    "work_items",
    "risks",
    "terms",
    "decisions",
    "contradictions",
}
_INTAKE_ASSUMPTION_FIELDS = {
    "tmp_handle",
    "intake_label",
    "statement",
    "status",
    "source_type",
    "source_excerpt",
    "blast_radius",
    "downstream_impact",
    "risk_if_wrong",
    "evidence_status",
    "depends_on",
    "external_fact",
}
_INTAKE_WORK_ITEM_FIELDS = {
    "tmp_handle",
    "derived_question_label",
    "kind",
    "question",
    "why_it_matters",
    "what_breaks_if_wrong",
    "blast_radius",
    "blocks_closure",
    "gap_type",
    "related_temp_refs",
    "source_assumption_refs",
    "answer_options",
    "recommended_default",
    "recommended_default_basis",
    "blocking_reason",
}
_INTERPRET_ASSUMPTION_FIELDS = _ASSUMPTION_FIELDS | {
    "evidence_status",
    "depends_on",
}
_INTERPRET_WORK_ITEM_FIELDS = _WORK_ITEM_FIELDS | {
    "derived_question_label",
    "gap_type",
    "source_assumption_refs",
    "blocking_reason",
}


def validate_output_schema(job: ModelJob | str, data: Any) -> dict[str, Any]:
    """Validate and return a defensive copy of a model output object."""
    resolved = ModelJob(job)
    if not isinstance(data, dict):
        raise SchemaError(["model output must be a JSON object"])
    copied = deepcopy(data)
    errors: list[str] = []
    if resolved == ModelJob.INITIAL_EXTRACTION:
        _validate_initial_extraction(copied, errors)
    elif resolved == ModelJob.INTAKE_UNSTRUCTURED_INPUT:
        _validate_intake_unstructured_input(copied, errors)
    elif resolved == ModelJob.RANK_NEXT_WORK_ITEM:
        _validate_rank_next_work_item(copied, errors)
    elif resolved == ModelJob.INTERPRET_USER_ANSWER:
        _validate_interpret_user_answer(copied, errors)
    elif resolved == ModelJob.CONTRADICTION_AUDIT:
        _validate_contradiction_audit(copied, errors)
    elif resolved == ModelJob.ARTIFACT_GENERATION:
        _validate_artifact_generation(copied, errors)
    if errors:
        raise SchemaError(errors)
    return copied


def _validate_initial_extraction(data: dict[str, Any], errors: list[str]) -> None:
    _exact_keys(data, _INITIAL_TOP, "initial_extraction", errors)
    for key in _INITIAL_TOP:
        _require_list(data, key, f"initial_extraction.{key}", errors)

    for index, item in enumerate(data.get("assumptions", [])):
        path = f"assumptions[{index}]"
        _creation_object(item, _ASSUMPTION_FIELDS, path, errors)
        _require_fields(
            item,
            {
                "tmp_handle",
                "statement",
                "status",
                "source_type",
                "source_excerpt",
                "blast_radius",
                "downstream_impact",
                "risk_if_wrong",
            },
            path,
            errors,
        )
        _enum(item, "status", AssumptionStatus, path, errors)
        _enum(item, "source_type", SourceType, path, errors)
        _enum(item, "blast_radius", BlastRadius, path, errors)
        if item.get("source_type") == SourceType.EXTERNAL_REQUIRED.value:
            if not _nonempty_string(item.get("external_fact")):
                errors.append(f"{path}.external_fact is required for external_required")

    for index, item in enumerate(data.get("work_items", [])):
        path = f"work_items[{index}]"
        _creation_object(item, _WORK_ITEM_FIELDS, path, errors)
        _require_fields(
            item,
            {
                "tmp_handle",
                "kind",
                "question",
                "why_it_matters",
                "what_breaks_if_wrong",
                "blast_radius",
                "blocks_closure",
                "related_temp_refs",
            },
            path,
            errors,
        )
        _enum(item, "kind", WorkItemKind, path, errors)
        _enum(item, "blast_radius", BlastRadius, path, errors)
        _require_bool(item, "blocks_closure", path, errors)
        _require_list(item, "related_temp_refs", path, errors)
        if "answer_options" in item:
            _require_list(item, "answer_options", path, errors)
            for option in item.get("answer_options", []):
                _enum_value(option, AnswerClass, f"{path}.answer_options", errors)

    for index, item in enumerate(data.get("risks", [])):
        path = f"risks[{index}]"
        _creation_object(item, _RISK_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "statement", "severity", "status"}, path, errors)
        _enum(item, "severity", Severity, path, errors)
        _enum(item, "status", RiskStatus, path, errors)
        if "source_refs" in item:
            _require_list(item, "source_refs", path, errors)

    for index, item in enumerate(data.get("terms", [])):
        path = f"terms[{index}]"
        _creation_object(item, _TERM_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "term", "status"}, path, errors)
        _enum(item, "status", TermStatus, path, errors)

    for index, item in enumerate(data.get("decisions", [])):
        path = f"decisions[{index}]"
        _creation_object(item, _DECISION_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "decision", "status"}, path, errors)
        _enum(item, "status", DecisionStatus, path, errors)

    for index, item in enumerate(data.get("contradictions", [])):
        path = f"contradictions[{index}]"
        _creation_object(item, _CONTRADICTION_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "refs", "severity", "description", "status"}, path, errors)
        _require_list(item, "refs", path, errors)
        _enum(item, "severity", Severity, path, errors)
        _enum(item, "status", ContradictionStatus, path, errors)


def _validate_intake_unstructured_input(data: dict[str, Any], errors: list[str]) -> None:
    _exact_keys(data, _INTAKE_TOP, "intake", errors)
    _validate_session_frame(data, errors)
    for key in ("assumptions", "work_items", "risks", "terms", "decisions", "contradictions"):
        _require_list(data, key, f"intake.{key}", errors)

    for index, item in enumerate(data.get("assumptions", [])):
        path = f"assumptions[{index}]"
        _creation_object(item, _INTAKE_ASSUMPTION_FIELDS, path, errors)
        _require_fields(
            item,
            {
                "tmp_handle",
                "intake_label",
                "statement",
                "status",
                "source_type",
                "source_excerpt",
                "blast_radius",
                "downstream_impact",
                "risk_if_wrong",
                "evidence_status",
            },
            path,
            errors,
        )
        if isinstance(item, dict):
            if item.get("status") != AssumptionStatus.CANDIDATE.value:
                errors.append(f"{path}.status must be candidate")
            _label(item.get("intake_label"), _CA_LABEL, f"{path}.intake_label", "CA-NN", errors)
            for field_name in ("statement", "downstream_impact", "risk_if_wrong"):
                if not _nonempty_string(item.get(field_name)):
                    errors.append(f"{path}.{field_name} must be a non-empty string")
            if "depends_on" in item:
                _require_list(item, "depends_on", path, errors)
        _enum(item, "source_type", SourceType, path, errors)
        _enum(item, "blast_radius", BlastRadius, path, errors)
        _enum(item, "evidence_status", EvidenceStatus, path, errors)
        if isinstance(item, dict) and item.get("source_type") == SourceType.EXTERNAL_REQUIRED.value:
            if not _nonempty_string(item.get("external_fact")):
                errors.append(f"{path}.external_fact is required for external_required")

    for index, item in enumerate(data.get("work_items", [])):
        path = f"work_items[{index}]"
        _creation_object(item, _INTAKE_WORK_ITEM_FIELDS, path, errors)
        _require_fields(
            item,
            {
                "tmp_handle",
                "kind",
                "question",
                "why_it_matters",
                "what_breaks_if_wrong",
                "blast_radius",
                "blocks_closure",
            },
            path,
            errors,
        )
        _enum(item, "kind", WorkItemKind, path, errors)
        _enum(item, "blast_radius", BlastRadius, path, errors)
        _require_bool(item, "blocks_closure", path, errors)
        if isinstance(item, dict):
            for field_name in ("question", "why_it_matters", "what_breaks_if_wrong"):
                if not _nonempty_string(item.get(field_name)):
                    errors.append(f"{path}.{field_name} must be a non-empty string")
            if item.get("derived_question_label") is not None:
                _label(
                    item.get("derived_question_label"),
                    _DQ_LABEL,
                    f"{path}.derived_question_label",
                    "DQ-NN",
                    errors,
                )
            if item.get("gap_type") is not None:
                _enum_value(item.get("gap_type"), GapType, f"{path}.gap_type", errors)
            for ref_field in ("related_temp_refs", "source_assumption_refs"):
                if ref_field in item:
                    _require_list(item, ref_field, path, errors)
            if "answer_options" in item:
                _require_list(item, "answer_options", path, errors)
                for option in item.get("answer_options", []):
                    _enum_value(option, AnswerClass, f"{path}.answer_options", errors)

    _validate_v1_style_creations(data, errors)


def _validate_session_frame(data: dict[str, Any], errors: list[str]) -> None:
    frame = data.get("session_frame")
    if not isinstance(frame, dict):
        errors.append("intake.session_frame must be an object")
        return
    _exact_keys(frame, _SESSION_FRAME_FIELDS, "session_frame", errors)
    for field_name in ("topic", "downstream_use", "closure_standard"):
        value = frame.get(field_name)
        if value is not None and not isinstance(value, str):
            errors.append(f"session_frame.{field_name} must be a string or null")
    input_mode = frame.get("input_mode")
    if input_mode not in _INPUT_MODES:
        errors.append(f"session_frame.input_mode has illegal value: {input_mode!r}")


def _validate_v1_style_creations(data: dict[str, Any], errors: list[str]) -> None:
    """Validate the risk/term/decision/contradiction creation lists (V1 shape)."""
    for index, item in enumerate(data.get("risks", [])):
        path = f"risks[{index}]"
        _creation_object(item, _RISK_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "statement", "severity", "status"}, path, errors)
        _enum(item, "severity", Severity, path, errors)
        _enum(item, "status", RiskStatus, path, errors)
        if "source_refs" in item:
            _require_list(item, "source_refs", path, errors)
    for index, item in enumerate(data.get("terms", [])):
        path = f"terms[{index}]"
        _creation_object(item, _TERM_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "term", "status"}, path, errors)
        _enum(item, "status", TermStatus, path, errors)
    for index, item in enumerate(data.get("decisions", [])):
        path = f"decisions[{index}]"
        _creation_object(item, _DECISION_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "decision", "status"}, path, errors)
        _enum(item, "status", DecisionStatus, path, errors)
    for index, item in enumerate(data.get("contradictions", [])):
        path = f"contradictions[{index}]"
        _creation_object(item, _CONTRADICTION_FIELDS, path, errors)
        _require_fields(item, {"tmp_handle", "refs", "severity", "description", "status"}, path, errors)
        _require_list(item, "refs", path, errors)
        _enum(item, "severity", Severity, path, errors)
        _enum(item, "status", ContradictionStatus, path, errors)


def _label(value: Any, pattern, path: str, form: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not pattern.match(value):
        errors.append(f"{path} must match {form}")


def _validate_rank_next_work_item(data: dict[str, Any], errors: list[str]) -> None:
    keys = {
        "selected_work_item_id",
        "question",
        "why_it_matters",
        "what_breaks_if_wrong",
        "tested_entity_id",
        "recommended_default",
        "recommended_default_basis",
        "allowed_answers",
    }
    _exact_keys(data, keys, "rank_next_work_item", errors)
    _require_fields(data, keys, "rank_next_work_item", errors)
    _require_list(data, "allowed_answers", "rank_next_work_item", errors)
    for option in data.get("allowed_answers", []):
        _enum_value(option, AnswerClass, "rank_next_work_item.allowed_answers", errors)


def _validate_interpret_user_answer(data: dict[str, Any], errors: list[str]) -> None:
    required = {"proposed_events", "followup_required", "warnings"}
    allowed = required | {"revision_required"}
    _known_keys(data, allowed, "interpret_user_answer", errors)
    _require_fields(data, required, "interpret_user_answer", errors)
    _require_list(data, "proposed_events", "interpret_user_answer", errors)
    _require_bool(data, "followup_required", "interpret_user_answer", errors)
    if "revision_required" in data:
        _require_bool(data, "revision_required", "interpret_user_answer", errors)
    _require_list(data, "warnings", "interpret_user_answer", errors)
    for index, item in enumerate(data.get("proposed_events", [])):
        path = f"proposed_events[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _exact_keys(item, {"event_type", "target_ref", "payload"}, path, errors)
        _require_fields(item, {"event_type", "target_ref", "payload"}, path, errors)
        event_type = item.get("event_type")
        if event_type not in {e.value for e in EventType}:
            errors.append(f"{path}.event_type is not a known event type: {event_type!r}")
        elif event_type not in INTERPRET_ALLOWED_EVENT_TYPES:
            errors.append(f"{path}.event_type is not permitted for interpret_user_answer")
        if not isinstance(item.get("payload"), dict):
            errors.append(f"{path}.payload must be an object")
        elif event_type in CREATION_EVENT_TYPES:
            if item.get("target_ref") != item["payload"].get("tmp_handle"):
                errors.append(f"{path}.target_ref must match the creation temp handle")
            _validate_creation_event_payload(event_type, item["payload"], path, errors)
        else:
            _validate_transition_payload(event_type, item.get("payload"), path, errors)


def _validate_contradiction_audit(data: dict[str, Any], errors: list[str]) -> None:
    keys = {
        "findings",
        "missing_provenance",
        "invalid_source_excerpts",
        "unresolved_high_blast_radius",
        "artifact_blockers",
    }
    _exact_keys(data, keys, "contradiction_audit", errors)
    for key in keys:
        _require_list(data, key, "contradiction_audit", errors)
    for index, finding in enumerate(data.get("findings", [])):
        path = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_fields(finding, {"kind", "refs", "severity", "description"}, path, errors)
        _require_list(finding, "refs", path, errors)
        _enum(finding, "severity", Severity, path, errors)


def _validate_artifact_generation(data: dict[str, Any], errors: list[str]) -> None:
    keys = {
        "artifact_markdown",
        "blocking_warnings",
        "open_risk_register",
        "traceability_summary",
    }
    _exact_keys(data, keys, "artifact_generation", errors)
    _require_fields(data, keys, "artifact_generation", errors)
    if not isinstance(data.get("artifact_markdown"), str):
        errors.append("artifact_generation.artifact_markdown must be a string")
    for key in ("blocking_warnings", "open_risk_register", "traceability_summary"):
        _require_list(data, key, "artifact_generation", errors)


def _validate_creation_event_payload(
    event_type: str, payload: dict[str, Any], path: str, errors: list[str]
) -> None:
    fields_by_event = {
        EventType.ASSUMPTION_CREATED.value: _INTERPRET_ASSUMPTION_FIELDS,
        EventType.TERM_CREATED.value: _TERM_FIELDS,
        EventType.DECISION_CREATED.value: _DECISION_FIELDS,
        EventType.RISK_CREATED.value: _RISK_FIELDS,
        EventType.CONTRADICTION_CREATED.value: _CONTRADICTION_FIELDS,
        EventType.WORK_ITEM_CREATED.value: _INTERPRET_WORK_ITEM_FIELDS,
    }
    _creation_object(payload, fields_by_event[event_type], f"{path}.payload", errors)
    if event_type == EventType.ASSUMPTION_CREATED.value:
        _require_fields(payload, {"tmp_handle", "statement", "status", "source_type", "source_excerpt", "blast_radius", "downstream_impact", "risk_if_wrong"}, f"{path}.payload", errors)
        _enum(payload, "status", AssumptionStatus, f"{path}.payload", errors)
        _enum(payload, "source_type", SourceType, f"{path}.payload", errors)
        _enum(payload, "blast_radius", BlastRadius, f"{path}.payload", errors)
        if "evidence_status" in payload:
            _enum(payload, "evidence_status", EvidenceStatus, f"{path}.payload", errors)
        if "depends_on" in payload:
            _require_list(payload, "depends_on", f"{path}.payload", errors)
        if payload.get("source_type") == SourceType.EXTERNAL_REQUIRED.value:
            if not _nonempty_string(payload.get("external_fact")):
                errors.append(f"{path}.payload.external_fact is required for external_required")
    elif event_type == EventType.WORK_ITEM_CREATED.value:
        _require_fields(payload, {"tmp_handle", "kind", "question", "why_it_matters", "what_breaks_if_wrong", "blast_radius", "blocks_closure"}, f"{path}.payload", errors)
        _enum(payload, "kind", WorkItemKind, f"{path}.payload", errors)
        _enum(payload, "blast_radius", BlastRadius, f"{path}.payload", errors)
        _require_bool(payload, "blocks_closure", f"{path}.payload", errors)
        if payload.get("derived_question_label") is not None:
            _label(
                payload.get("derived_question_label"),
                _DQ_LABEL,
                f"{path}.payload.derived_question_label",
                "DQ-NN",
                errors,
            )
        if payload.get("gap_type") is not None:
            _enum_value(payload.get("gap_type"), GapType, f"{path}.payload.gap_type", errors)
        if "source_assumption_refs" in payload:
            _require_list(payload, "source_assumption_refs", f"{path}.payload", errors)
        if "related_temp_refs" in payload:
            _require_list(payload, "related_temp_refs", f"{path}.payload", errors)
        if "answer_options" in payload:
            _require_list(payload, "answer_options", f"{path}.payload", errors)
            for option in payload.get("answer_options", []):
                _enum_value(option, AnswerClass, f"{path}.payload.answer_options", errors)
    elif event_type == EventType.RISK_CREATED.value:
        _require_fields(payload, {"tmp_handle", "statement", "severity", "status"}, f"{path}.payload", errors)
        _enum(payload, "severity", Severity, f"{path}.payload", errors)
        _enum(payload, "status", RiskStatus, f"{path}.payload", errors)
    elif event_type == EventType.TERM_CREATED.value:
        _require_fields(payload, {"tmp_handle", "term", "status"}, f"{path}.payload", errors)
        _enum(payload, "status", TermStatus, f"{path}.payload", errors)
    elif event_type == EventType.DECISION_CREATED.value:
        _require_fields(payload, {"tmp_handle", "decision", "status"}, f"{path}.payload", errors)
        _enum(payload, "status", DecisionStatus, f"{path}.payload", errors)
    elif event_type == EventType.CONTRADICTION_CREATED.value:
        _require_fields(payload, {"tmp_handle", "refs", "severity", "description", "status"}, f"{path}.payload", errors)
        _require_list(payload, "refs", f"{path}.payload", errors)
        _enum(payload, "severity", Severity, f"{path}.payload", errors)
        _enum(payload, "status", ContradictionStatus, f"{path}.payload", errors)


def _validate_transition_payload(event_type: str, payload: Any, path: str, errors: list[str]) -> None:
    if not isinstance(payload, dict):
        return
    _require_fields(payload, {"from", "to", "reason"}, f"{path}.payload", errors)
    allowed = {"from", "to", "reason", "user_answer_event", "prior_statement", "new_statement", "deferred_reason", "resolution_work_item"}
    unknown = set(payload) - allowed
    if unknown:
        errors.append(f"{path}.payload has unknown fields: {sorted(unknown)!r}")


def _creation_object(
    item: Any, allowed_fields: set[str], path: str, errors: list[str]
) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    unknown = set(item) - allowed_fields
    if unknown:
        errors.append(f"{path} has unknown fields: {sorted(unknown)!r}")
    if "id" in item:
        errors.append(f"{path}.id is not allowed in creation output")
    if not IdAllocator.is_temp_handle(item.get("tmp_handle")):
        errors.append(f"{path}.tmp_handle must be a temp handle")


def _exact_keys(
    item: dict[str, Any], required_keys: set[str], path: str, errors: list[str]
) -> None:
    missing = required_keys - set(item)
    unknown = set(item) - required_keys
    if missing:
        errors.append(f"{path} missing required fields: {sorted(missing)!r}")
    if unknown:
        errors.append(f"{path} has unknown fields: {sorted(unknown)!r}")


def _known_keys(
    item: dict[str, Any], allowed_keys: set[str], path: str, errors: list[str]
) -> None:
    unknown = set(item) - allowed_keys
    if unknown:
        errors.append(f"{path} has unknown fields: {sorted(unknown)!r}")


def _require_fields(
    item: Any, fields: set[str], path: str, errors: list[str]
) -> None:
    if not isinstance(item, dict):
        return
    missing = fields - set(item)
    if missing:
        errors.append(f"{path} missing required fields: {sorted(missing)!r}")


def _require_list(item: Any, field: str, path: str, errors: list[str]) -> None:
    if isinstance(item, dict) and not isinstance(item.get(field), list):
        errors.append(f"{path}.{field} must be a list")


def _require_bool(item: Any, field: str, path: str, errors: list[str]) -> None:
    if isinstance(item, dict) and not isinstance(item.get(field), bool):
        errors.append(f"{path}.{field} must be a boolean")


def _enum(item: dict[str, Any], field: str, enum_type, path: str, errors: list[str]) -> None:
    if field in item:
        _enum_value(item[field], enum_type, f"{path}.{field}", errors)


def _enum_value(value: Any, enum_type, path: str, errors: list[str]) -> None:
    if value not in {member.value for member in enum_type}:
        errors.append(f"{path} has illegal enum value: {value!r}")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _walk_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value
