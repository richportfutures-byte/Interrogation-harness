"""Gemini API model adapter for live harness runs.

The adapter is intentionally thin: it returns only the raw model text. The harness
continues to own parsing, validation, retry handling, event recording, and all state
mutation.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from interrogation_harness import canonical
from interrogation_harness.model.adapter import ModelAdapter, ModelJob, ModelRequest
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


GeminiTransport = Callable[[str, Mapping[str, str], dict[str, Any], float], dict[str, Any]]


class GeminiAdapterError(RuntimeError):
    """Raised when Gemini cannot produce a raw text response."""


@dataclass(frozen=True)
class GeminiModelAdapter(ModelAdapter):
    """Live Gemini adapter using the Interactions API.

    Defaults target the stable production model and stable API version. Per-job thinking
    levels are deliberately explicit so important audit jobs get more reasoning while
    routine ranking stays cheaper.
    """

    api_key: str
    model: str = "gemini-3.5-flash"
    api_base: str = "https://generativelanguage.googleapis.com"
    api_version: str = "v1"
    timeout_seconds: float = 120.0
    max_output_tokens: int | None = 65536
    temperature: float | None = None
    thinking_level: str | None = None
    transport: GeminiTransport | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "GeminiModelAdapter":
        env = os.environ if environ is None else environ
        api_key = env.get("GEMINI_API_KEY")
        if not api_key:
            raise GeminiAdapterError("GEMINI_API_KEY is required for the Gemini adapter")
        return cls(
            api_key=api_key,
            model=env.get("GEMINI_MODEL", "gemini-3.5-flash"),
            api_base=env.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com"),
            api_version=env.get("GEMINI_API_VERSION", "v1"),
            timeout_seconds=float(env.get("GEMINI_TIMEOUT_SECONDS", "120")),
            max_output_tokens=_optional_int(env.get("GEMINI_MAX_OUTPUT_TOKENS"), 65536),
            temperature=_optional_float(env.get("GEMINI_TEMPERATURE")),
            thinking_level=env.get("GEMINI_THINKING_LEVEL"),
        )

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        if scenario is not None:
            raise GeminiAdapterError("GeminiModelAdapter does not support mock scenarios")
        body = self._interaction_body(request)
        response = self._transport(self._url(), self._headers(), body, self.timeout_seconds)
        return _extract_output_text(response)

    def _url(self) -> str:
        return f"{self.api_base.rstrip('/')}/{self.api_version.strip('/')}/interactions"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _transport(
        self, url: str, headers: Mapping[str, str], body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        if self.transport is not None:
            return self.transport(url, headers, body, timeout)
        return _post_json(url, headers, body, timeout)

    def _interaction_body(self, request: ModelRequest) -> dict[str, Any]:
        generation_config = _generation_config(
            request.job,
            self.thinking_level,
            self.temperature,
            self.max_output_tokens,
        )
        body: dict[str, Any] = {
            "model": self.model,
            "input": _job_prompt(request),
            "system_instruction": _SYSTEM_INSTRUCTION,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema_for_job(request.job),
            },
            "store": False,
        }
        if generation_config:
            body["generation_config"] = generation_config
        return body


def _post_json(
    url: str, headers: Mapping[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GeminiAdapterError(f"Gemini API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GeminiAdapterError(f"Gemini API request failed: {exc.reason}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiAdapterError(f"Gemini API returned non-JSON response: {exc.msg}") from exc


def _extract_output_text(response: dict[str, Any]) -> str:
    status = response.get("status")
    if status not in (None, "completed"):
        raise GeminiAdapterError(f"Gemini interaction did not complete: {status!r}")
    parts: list[str] = []
    for step in response.get("steps", []):
        if step.get("type") != "model_output":
            continue
        for content in step.get("content", []):
            if content.get("type") == "text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    text = "".join(parts).strip()
    if not text:
        raise GeminiAdapterError("Gemini response did not contain model output text")
    return text


_SYSTEM_INSTRUCTION = (
    "You are the model proposal layer inside a local event-sourced interrogation "
    "harness. Return only a single JSON object matching the response schema. Do not "
    "wrap JSON in markdown. The harness, not you, owns durable IDs, validation, state "
    "transitions, and persistence. Use temporary handles for creations. Never invent "
    "verified user provenance: source excerpts must be exact substrings of the input "
    "text when source_type is user_stated."
)


def _job_prompt(request: ModelRequest) -> str:
    payload = _plain(request.payload)
    return (
        f"Job: {request.job.value}\n\n"
        f"{_job_instructions(request.job)}\n\n"
        "Request payload JSON:\n"
        f"{canonical.dumps_ledger(payload)}"
    )


def _job_instructions(job: ModelJob) -> str:
    if job == ModelJob.INITIAL_EXTRACTION:
        return (
            "Inspect source_markdown and propose V1 assumptions, work items, risks, "
            "terms, decisions, and contradictions. Use tmp_assumption_N, tmp_work_N, "
            "tmp_risk_N, tmp_term_N, tmp_decision_N, and tmp_contradiction_N handles. "
            "High blast-radius work must set blocks_closure true."
        )
    if job == ModelJob.INTAKE_UNSTRUCTURED_INPUT:
        return (
            "Run V2 unstructured intake. Extract candidate assumptions labeled CA-01, "
            "CA-02, and so on. Generate material derived questions labeled DQ-01, "
            "DQ-02, and so on, using gap_type values from the schema. High blast-radius "
            "work must block closure. Medium blocking work must include blocking_reason. "
            "Low work must not block closure. Mark uncertainty with evidence_status."
        )
    if job == ModelJob.RANK_NEXT_WORK_ITEM:
        return (
            "Select exactly one unresolved work item. If any work item is already active, "
            "select that item. If unresolved closure blockers exist, select a blocker."
        )
    if job == ModelJob.INTERPRET_USER_ANSWER:
        return (
            "Interpret the active work item's user_answer into proposed creation or "
            "transition events. For V2 projections include revision_required. Transition "
            "only the active work item for WORK_ITEM_STATUS_CHANGED. Preserve revisions "
            "with prior_statement and new_statement. Ambiguous answers must not lock."
        )
    if job == ModelJob.CONTRADICTION_AUDIT:
        return (
            "Audit the projection and source for contradictions, missing provenance, "
            "invalid excerpts, unresolved high-blast-radius work, and artifact blockers."
        )
    if job == ModelJob.BLIND_SPOT_AUDIT:
        return (
            "Run the V2 blind-spot audit. Convert material findings into work_item, "
            "risk, contradiction, assumption, or no_op conversion targets. Use existing "
            "durable refs only; do not create IDs. High work blocks closure, medium "
            "blocking work needs blocking_reason, and low work must not block closure."
        )
    if job == ModelJob.ARTIFACT_GENERATION:
        return (
            "Generate the final artifact from the projection only. Do not invent locked "
            "assumptions. Surface unresolved blockers and open risks. For V2 include "
            "closure_status that matches the projection."
        )
    raise GeminiAdapterError(f"unsupported model job: {job.value}")


def _generation_config(
    job: ModelJob,
    override_thinking_level: str | None,
    temperature: float | None,
    max_output_tokens: int | None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "thinking_level": override_thinking_level or _thinking_level_for_job(job),
        "thinking_summaries": "none",
    }
    if temperature is not None:
        config["temperature"] = temperature
    if max_output_tokens is not None:
        config["max_output_tokens"] = max_output_tokens
    return config


def _thinking_level_for_job(job: ModelJob) -> str:
    return {
        ModelJob.RANK_NEXT_WORK_ITEM: "medium",
        ModelJob.ARTIFACT_GENERATION: "medium",
    }.get(job, "high")


def _optional_int(value: str | None, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    if value.lower() == "none":
        return None
    return int(value)


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _plain(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_plain(item) for item in value)
    return value


def schema_for_job(job: ModelJob | str) -> dict[str, Any]:
    resolved = ModelJob(job)
    if resolved == ModelJob.INITIAL_EXTRACTION:
        return _initial_extraction_schema(v2=False)
    if resolved == ModelJob.INTAKE_UNSTRUCTURED_INPUT:
        return _initial_extraction_schema(v2=True)
    if resolved == ModelJob.RANK_NEXT_WORK_ITEM:
        return _rank_schema()
    if resolved == ModelJob.INTERPRET_USER_ANSWER:
        return _interpret_schema()
    if resolved == ModelJob.CONTRADICTION_AUDIT:
        return _contradiction_audit_schema()
    if resolved == ModelJob.BLIND_SPOT_AUDIT:
        return _blind_spot_schema()
    if resolved == ModelJob.ARTIFACT_GENERATION:
        return _artifact_schema()
    raise GeminiAdapterError(f"unsupported model job: {resolved.value}")


def _initial_extraction_schema(*, v2: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "assumptions": _array(_assumption_creation_schema(v2=v2)),
        "work_items": _array(_work_item_creation_schema(v2=v2)),
        "risks": _array(_risk_creation_schema()),
        "terms": _array(_term_creation_schema()),
        "decisions": _array(_decision_creation_schema()),
        "contradictions": _array(_contradiction_creation_schema()),
    }
    required = list(properties)
    if v2:
        properties = {"session_frame": _session_frame_schema(), **properties}
        required = list(properties)
    return _object(properties, required)


def _session_frame_schema() -> dict[str, Any]:
    return _object(
        {
            "topic": _nullable_string(),
            "downstream_use": _nullable_string(),
            "closure_standard": _nullable_string(),
            "input_mode": _enum(["structured", "unstructured", "mixed"]),
        },
        ["topic", "downstream_use", "closure_standard", "input_mode"],
    )


def _assumption_creation_schema(*, v2: bool) -> dict[str, Any]:
    properties = {
        "tmp_handle": _string("Temporary creation handle, e.g. tmp_assumption_1."),
        "statement": _string(),
        "status": _enum([AssumptionStatus.CANDIDATE.value]),
        "source_type": _enum_values(SourceType),
        "source_excerpt": _nullable_string(),
        "blast_radius": _enum_values(BlastRadius),
        "downstream_impact": _string(),
        "risk_if_wrong": _string(),
        "external_fact": _string(),
    }
    required = [
        "tmp_handle",
        "statement",
        "status",
        "source_type",
        "source_excerpt",
        "blast_radius",
        "downstream_impact",
        "risk_if_wrong",
    ]
    if v2:
        properties.update(
            {
                "intake_label": _string("CA-NN label."),
                "evidence_status": _enum_values(EvidenceStatus),
                "depends_on": _array(_string()),
            }
        )
        required.extend(["intake_label", "evidence_status"])
    return _object(properties, required)


def _work_item_creation_schema(*, v2: bool) -> dict[str, Any]:
    properties = {
        "tmp_handle": _string("Temporary creation handle, e.g. tmp_work_1."),
        "kind": _enum_values(WorkItemKind),
        "question": _string(),
        "why_it_matters": _string(),
        "what_breaks_if_wrong": _string(),
        "blast_radius": _enum_values(BlastRadius),
        "blocks_closure": {"type": "boolean"},
        "related_temp_refs": _array(_string()),
        "answer_options": _array(_enum_values(AnswerClass)),
        "recommended_default": _nullable_string(),
        "recommended_default_basis": _nullable_string(),
    }
    required = [
        "tmp_handle",
        "kind",
        "question",
        "why_it_matters",
        "what_breaks_if_wrong",
        "blast_radius",
        "blocks_closure",
    ]
    if not v2:
        required.append("related_temp_refs")
    if v2:
        properties.update(
            {
                "derived_question_label": _nullable_string(),
                "gap_type": _enum_values(GapType),
                "source_assumption_refs": _array(_string()),
                "blocking_reason": _nullable_string(),
            }
        )
    return _object(properties, required)


def _risk_creation_schema() -> dict[str, Any]:
    return _object(
        {
            "tmp_handle": _string(),
            "statement": _string(),
            "severity": _enum_values(Severity),
            "status": _enum_values(RiskStatus),
            "source_refs": _array(_string()),
        },
        ["tmp_handle", "statement", "severity", "status"],
    )


def _term_creation_schema() -> dict[str, Any]:
    return _object(
        {
            "tmp_handle": _string(),
            "term": _string(),
            "definition": _nullable_string(),
            "status": _enum_values(TermStatus),
        },
        ["tmp_handle", "term", "status"],
    )


def _decision_creation_schema() -> dict[str, Any]:
    return _object(
        {
            "tmp_handle": _string(),
            "decision": _string(),
            "rationale": _nullable_string(),
            "status": _enum_values(DecisionStatus),
        },
        ["tmp_handle", "decision", "status"],
    )


def _contradiction_creation_schema() -> dict[str, Any]:
    return _object(
        {
            "tmp_handle": _string(),
            "refs": _array(_string()),
            "severity": _enum_values(Severity),
            "description": _string(),
            "status": _enum_values(ContradictionStatus),
        },
        ["tmp_handle", "refs", "severity", "description", "status"],
    )


def _rank_schema() -> dict[str, Any]:
    return _object(
        {
            "selected_work_item_id": _string(),
            "question": _string(),
            "why_it_matters": _string(),
            "what_breaks_if_wrong": _string(),
            "tested_entity_id": _nullable_string(),
            "recommended_default": _nullable_string(),
            "recommended_default_basis": _nullable_string(),
            "allowed_answers": _array(_enum_values(AnswerClass)),
        },
        [
            "selected_work_item_id",
            "question",
            "why_it_matters",
            "what_breaks_if_wrong",
            "tested_entity_id",
            "recommended_default",
            "recommended_default_basis",
            "allowed_answers",
        ],
    )


def _interpret_schema() -> dict[str, Any]:
    event_schema = _object(
        {
            "event_type": _string(),
            "target_ref": _string(),
            "payload": {"type": "object", "additionalProperties": True},
        },
        ["event_type", "target_ref", "payload"],
    )
    return _object(
        {
            "proposed_events": _array(event_schema),
            "followup_required": {"type": "boolean"},
            "revision_required": {"type": "boolean"},
            "warnings": _array(_string()),
        },
        ["proposed_events", "followup_required", "warnings"],
    )


def _contradiction_audit_schema() -> dict[str, Any]:
    finding = _object(
        {
            "kind": _enum(["contradiction"]),
            "refs": _array(_string()),
            "severity": _enum_values(Severity),
            "description": _string(),
        },
        ["kind", "refs", "severity", "description"],
    )
    return _object(
        {
            "findings": _array(finding),
            "missing_provenance": _array(_string()),
            "invalid_source_excerpts": _array(_string()),
            "unresolved_high_blast_radius": _array(_string()),
            "artifact_blockers": _array({"type": "object", "additionalProperties": True}),
        },
        [
            "findings",
            "missing_provenance",
            "invalid_source_excerpts",
            "unresolved_high_blast_radius",
            "artifact_blockers",
        ],
    )


def _blind_spot_schema() -> dict[str, Any]:
    finding = _object(
        {
            "category": _string(),
            "kind": _string(),
            "refs": _array(_string()),
            "severity": _enum_values(Severity),
            "description": _string(),
            "conversion_target": _enum(["work_item", "risk", "contradiction", "assumption", "no_op"]),
            "blocks_closure": {"type": "boolean"},
            "work_item": _audit_work_item_schema(),
            "risk": _audit_risk_schema(),
            "contradiction": _audit_contradiction_schema(),
            "assumption": _audit_assumption_schema(),
            "covered_by": _array(_string()),
        },
        ["category", "refs", "severity", "description", "conversion_target"],
    )
    return _object(
        {
            "findings": _array(finding),
            "missing_provenance": _array(_string()),
            "invalid_source_excerpts": _array(_string()),
            "unresolved_material_work": _array(_string()),
            "artifact_blockers": _array({"type": "object", "additionalProperties": True}),
        },
        [
            "findings",
            "missing_provenance",
            "invalid_source_excerpts",
            "unresolved_material_work",
            "artifact_blockers",
        ],
    )


def _audit_work_item_schema() -> dict[str, Any]:
    return _object(
        {
            "kind": _enum_values(WorkItemKind),
            "question": _string(),
            "why_it_matters": _string(),
            "what_breaks_if_wrong": _string(),
            "blast_radius": _enum_values(BlastRadius),
            "blocks_closure": {"type": "boolean"},
            "gap_type": _enum_values(GapType),
            "related_refs": _array(_string()),
            "source_assumption_refs": _array(_string()),
            "answer_options": _array(_enum_values(AnswerClass)),
            "recommended_default": _nullable_string(),
            "recommended_default_basis": _nullable_string(),
            "blocking_reason": _nullable_string(),
        },
        ["kind", "question", "why_it_matters", "what_breaks_if_wrong", "blast_radius", "blocks_closure"],
    )


def _audit_risk_schema() -> dict[str, Any]:
    return _object(
        {
            "statement": _string(),
            "severity": _enum_values(Severity),
            "status": _enum_values(RiskStatus),
            "source_refs": _array(_string()),
        },
        ["statement", "severity", "status"],
    )


def _audit_contradiction_schema() -> dict[str, Any]:
    return _object(
        {
            "refs": _array(_string()),
            "severity": _enum_values(Severity),
            "description": _string(),
            "status": _enum_values(ContradictionStatus),
        },
        ["refs", "severity", "description", "status"],
    )


def _audit_assumption_schema() -> dict[str, Any]:
    return _object(
        {
            "statement": _string(),
            "status": _enum_values(AssumptionStatus),
            "source_type": _enum_values(SourceType),
            "source_excerpt": _nullable_string(),
            "blast_radius": _enum_values(BlastRadius),
            "downstream_impact": _string(),
            "risk_if_wrong": _string(),
            "evidence_status": _enum_values(EvidenceStatus),
            "depends_on": _array(_string()),
            "external_fact": _string(),
        },
        [
            "statement",
            "status",
            "source_type",
            "source_excerpt",
            "blast_radius",
            "downstream_impact",
            "risk_if_wrong",
            "evidence_status",
        ],
    )


def _artifact_schema() -> dict[str, Any]:
    closure = _object(
        {
            "mode": _enum(["open", "force_closed"]),
            "complete": {"type": "boolean"},
            "force_closed_event": _nullable_string(),
        },
        ["mode", "complete", "force_closed_event"],
    )
    return _object(
        {
            "artifact_markdown": _string(),
            "blocking_warnings": _array(_string()),
            "open_risk_register": _array({"type": "object", "additionalProperties": True}),
            "traceability_summary": _array({"type": "object", "additionalProperties": True}),
            "closure_status": closure,
        },
        ["artifact_markdown", "blocking_warnings", "open_risk_register", "traceability_summary"],
    )


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _string(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if description:
        schema["description"] = description
    return schema


def _nullable_string() -> dict[str, Any]:
    return {"type": ["string", "null"]}


def _enum(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


def _enum_values(enum_cls: Any) -> dict[str, Any]:
    return _enum([item.value for item in enum_cls])
