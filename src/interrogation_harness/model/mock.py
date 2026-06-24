"""Deterministic offline model used by tests and the acceptance suite."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from interrogation_harness import canonical
from interrogation_harness.model.adapter import ModelAdapter, ModelJob, ModelRequest


class MockScenario(str, Enum):
    """Named canned responses supplied by the deterministic mock."""

    INITIAL_EXTRACTION = "initial_extraction"
    RANK_NEXT_WORK_ITEM = "rank_next_work_item"
    INTERPRET_CONFIRM = "interpret_user_answer:confirm"
    INTERPRET_REJECT = "interpret_user_answer:reject"
    INTERPRET_REVISE = "interpret_user_answer:revise"
    INTERPRET_DEFER = "interpret_user_answer:defer"
    INTERPRET_UNKNOWN = "interpret_user_answer:unknown"
    CONTRADICTION_AUDIT = "contradiction_audit"
    ARTIFACT_GENERATION = "artifact_generation"
    MALFORMED_JSON = "malformed_json"
    ILLEGAL_TRANSITION = "illegal_transition"
    CREATION_WITH_DURABLE_ID = "creation_with_durable_id"
    # V2 intake scenarios (V2 spec Section 8).
    INTAKE_VALID = "intake_unstructured_input"
    INTAKE_DURABLE_ID = "intake_durable_id_in_creation"
    INTAKE_HIGH_NOT_BLOCKING = "intake_high_blast_not_blocking"
    INTAKE_DQ_WITHOUT_SOURCE = "intake_dq_without_source"
    INTAKE_INVALID_ENUM = "intake_invalid_enum"
    INTAKE_BAD_SESSION_FRAME = "intake_missing_session_frame"
    INTAKE_UNVERIFIABLE_EXCERPT = "intake_unverifiable_excerpt"
    # V2 blind-spot audit scenarios (Pass D).
    BLIND_SPOT_AUDIT_NO_FINDINGS = "blind_spot_audit:no_findings"
    BLIND_SPOT_AUDIT_AUTHORITY_CONFUSION = "blind_spot_audit:authority_confusion"
    BLIND_SPOT_AUDIT_FAILURE_PATH = "blind_spot_audit:failure_path_omission"
    BLIND_SPOT_AUDIT_EXTERNAL_VALIDATION = "blind_spot_audit:external_validation"
    BLIND_SPOT_AUDIT_UNDECIDABLE = "blind_spot_audit:undecidable"
    BLIND_SPOT_AUDIT_CONTRADICTION = "blind_spot_audit:contradiction"
    BLIND_SPOT_AUDIT_COVERED = "blind_spot_audit:covered"
    BLIND_SPOT_AUDIT_HIGH_NONBLOCKING = "blind_spot_audit:high_nonblocking"
    BLIND_SPOT_AUDIT_MEDIUM_BLOCKING_NO_REASON = (
        "blind_spot_audit:medium_blocking_no_reason"
    )
    BLIND_SPOT_AUDIT_LOW_BLOCKING = "blind_spot_audit:low_blocking"
    BLIND_SPOT_AUDIT_NONEXISTENT_COVERED = "blind_spot_audit:nonexistent_covered"
    BLIND_SPOT_AUDIT_DURABLE_ID = "blind_spot_audit:durable_id"
    BLIND_SPOT_AUDIT_MISSING_CONVERSION = "blind_spot_audit:missing_conversion"


def _raw_json(obj: dict[str, Any]) -> str:
    """Return stable raw JSON without validating the proposal."""
    return canonical.dumps_event_line(obj)


RESPONSES: dict[MockScenario, str] = {
    MockScenario.INITIAL_EXTRACTION: _raw_json(
        {
            "assumptions": [
                {
                    "tmp_handle": "tmp_assumption_1",
                    "statement": "Payments require idempotency keys.",
                    "status": "candidate",
                    "source_type": "user_stated",
                    "source_excerpt": "Payments require idempotency keys.",
                    "blast_radius": "high",
                    "downstream_impact": "Payment retries and duplicate prevention",
                    "risk_if_wrong": "Duplicate charges or corrupted payment state",
                },
                {
                    "tmp_handle": "tmp_assumption_2",
                    "statement": "Operators can tolerate manual force close.",
                    "status": "candidate",
                    "source_type": "model_inferred",
                    "source_excerpt": None,
                    "blast_radius": "medium",
                    "downstream_impact": "Closure workflow",
                    "risk_if_wrong": "Incomplete handoff expectations",
                },
            ],
            "work_items": [
                {
                    "tmp_handle": "tmp_work_1",
                    "kind": "resolve_assumption",
                    "question": "Should payment retries be idempotent?",
                    "why_it_matters": "It controls duplicate side effects.",
                    "what_breaks_if_wrong": "A retry can create two payments.",
                    "blast_radius": "high",
                    "blocks_closure": True,
                    "related_temp_refs": ["tmp_assumption_1"],
                    "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
                }
            ],
            "risks": [],
            "terms": [],
            "decisions": [],
            "contradictions": [],
        }
    ),
    MockScenario.RANK_NEXT_WORK_ITEM: _raw_json(
        {
            "selected_work_item_id": "W-0001",
            "question": "Should payment retries be idempotent?",
            "why_it_matters": "It controls duplicate side effects.",
            "what_breaks_if_wrong": "A retry can create two payments.",
            "tested_entity_id": "A-0001",
            "recommended_default": None,
            "recommended_default_basis": None,
            "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
        }
    ),
    MockScenario.INTERPRET_CONFIRM: _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": "A-0001",
                    "payload": {
                        "from": "provisional",
                        "to": "locked",
                        "reason": "User confirmed the active assumption.",
                    },
                },
                {
                    "event_type": "WORK_ITEM_STATUS_CHANGED",
                    "target_ref": "W-0001",
                    "payload": {
                        "from": "active",
                        "to": "answered",
                        "reason": "Answer interpreted as confirm.",
                    },
                },
            ],
            "followup_required": False,
            "warnings": [],
        }
    ),
    MockScenario.INTERPRET_REJECT: _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": "A-0001",
                    "payload": {
                        "from": "candidate",
                        "to": "rejected",
                        "reason": "User rejected the assumption.",
                    },
                }
            ],
            "followup_required": False,
            "warnings": [],
        }
    ),
    MockScenario.INTERPRET_REVISE: _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": "A-0001",
                    "payload": {
                        "from": "locked",
                        "to": "revised",
                        "reason": "User supplied a corrected statement.",
                        "prior_statement": "Payments require idempotency keys.",
                        "new_statement": "Payment writes require idempotency keys.",
                    },
                }
            ],
            "followup_required": False,
            "warnings": [],
        }
    ),
    MockScenario.INTERPRET_DEFER: _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "WORK_ITEM_STATUS_CHANGED",
                    "target_ref": "W-0001",
                    "payload": {
                        "from": "active",
                        "to": "deferred",
                        "reason": "User deferred the question.",
                    },
                }
            ],
            "followup_required": False,
            "warnings": ["Question deferred, closure remains blocked if high blast radius."],
        }
    ),
    MockScenario.INTERPRET_UNKNOWN: _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "RISK_CREATED",
                    "target_ref": "tmp_risk_1",
                    "payload": {
                        "tmp_handle": "tmp_risk_1",
                        "statement": "Idempotency behavior is unknown.",
                        "severity": "high",
                        "status": "open",
                        "source_refs": ["A-0001"],
                    },
                },
                {
                    "event_type": "WORK_ITEM_STATUS_CHANGED",
                    "target_ref": "W-0001",
                    "payload": {
                        "from": "active",
                        "to": "deferred",
                        "reason": "User answered unknown.",
                    },
                },
            ],
            "followup_required": False,
            "warnings": ["Unknown answer routed to an open risk."],
        }
    ),
    MockScenario.CONTRADICTION_AUDIT: _raw_json(
        {
            "findings": [
                {
                    "kind": "contradiction",
                    "refs": ["A-0001", "A-0002"],
                    "severity": "medium",
                    "description": "One assumption requires retries, another implies single attempt only.",
                }
            ],
            "missing_provenance": [],
            "invalid_source_excerpts": [],
            "unresolved_high_blast_radius": ["W-0001"],
            "artifact_blockers": [],
        }
    ),
    MockScenario.ARTIFACT_GENERATION: _raw_json(
        {
            "artifact_markdown": (
                "# Final Artifact\n\n"
                "## Locked Assumptions\n\n"
                "- Payment writes require idempotency keys.\n\n"
                "## Open Risk Register\n\n"
                "- Idempotency behavior must remain visible until resolved.\n"
            ),
            "blocking_warnings": [],
            "open_risk_register": [
                {
                    "id": "R-0001",
                    "statement": "Idempotency behavior is unknown.",
                    "severity": "high",
                }
            ],
            "traceability_summary": [
                {"entity_id": "A-0001", "source": "user_stated", "verified": True}
            ],
        }
    ),
    MockScenario.MALFORMED_JSON: '{"proposed_events": [',
    MockScenario.ILLEGAL_TRANSITION: _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": "A-0001",
                    "payload": {
                        "from": "rejected",
                        "to": "locked",
                        "reason": "Deliberately illegal mock proposal.",
                    },
                }
            ],
            "followup_required": False,
            "warnings": [],
        }
    ),
    MockScenario.CREATION_WITH_DURABLE_ID: _raw_json(
        {
            "assumptions": [
                {
                    "id": "A-0001",
                    "tmp_handle": "tmp_assumption_1",
                    "statement": "This creation wrongly contains a durable ID.",
                    "status": "candidate",
                    "source_type": "model_inferred",
                    "source_excerpt": None,
                    "blast_radius": "high",
                    "downstream_impact": "Identity ownership",
                    "risk_if_wrong": "The model can appear to mint durable identity.",
                }
            ],
            "work_items": [],
            "risks": [],
            "terms": [],
            "decisions": [],
            "contradictions": [],
        }
    ),
}


def _valid_intake() -> dict[str, Any]:
    """A fully valid V2 intake response (CA-01 user_stated, CA-02 model_inferred, one DQ)."""
    return {
        "session_frame": {
            "topic": "payment retries",
            "downstream_use": "implementation",
            "closure_standard": "all high blast radius assumptions locked",
            "input_mode": "unstructured",
        },
        "assumptions": [
            {
                "tmp_handle": "tmp_assumption_1",
                "intake_label": "CA-01",
                "statement": "Payments require idempotency keys.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": "Payments require idempotency keys.",
                "blast_radius": "high",
                "downstream_impact": "Payment retries and duplicate prevention",
                "risk_if_wrong": "Duplicate charges or corrupted payment state",
                "evidence_status": "verified_user_stated",
            },
            {
                "tmp_handle": "tmp_assumption_2",
                "intake_label": "CA-02",
                "statement": "Operators tolerate manual force close.",
                "status": "candidate",
                "source_type": "model_inferred",
                "source_excerpt": None,
                "blast_radius": "medium",
                "downstream_impact": "Closure workflow",
                "risk_if_wrong": "Incomplete handoff expectations",
                "evidence_status": "model_inferred",
            },
        ],
        "work_items": [
            {
                "tmp_handle": "tmp_work_1",
                "derived_question_label": "DQ-01",
                "kind": "resolve_assumption",
                "question": "If a payment retry fires, what guarantees idempotency?",
                "why_it_matters": "It controls duplicate side effects.",
                "what_breaks_if_wrong": "A retry can create two payments.",
                "blast_radius": "high",
                "blocks_closure": True,
                "gap_type": "failure_mode",
                "source_assumption_refs": ["tmp_assumption_1"],
                "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
            }
        ],
        "risks": [],
        "terms": [],
        "decisions": [],
        "contradictions": [],
    }


def _intake_durable_id() -> dict[str, Any]:
    data = _valid_intake()
    data["assumptions"][0]["id"] = "A-0001"
    return data


def _intake_high_not_blocking() -> dict[str, Any]:
    data = _valid_intake()
    data["work_items"][0]["blocks_closure"] = False
    return data


def _intake_dq_without_source() -> dict[str, Any]:
    data = _valid_intake()
    work_item = data["work_items"][0]
    work_item["blast_radius"] = "medium"
    work_item["blocks_closure"] = False
    work_item.pop("source_assumption_refs", None)
    return data


def _intake_invalid_enum() -> dict[str, Any]:
    data = _valid_intake()
    data["assumptions"][0]["evidence_status"] = "totally_invalid"
    return data


def _intake_bad_session_frame() -> dict[str, Any]:
    data = _valid_intake()
    data["session_frame"] = {"topic": "x", "downstream_use": "y", "input_mode": "bogus"}
    return data


def _intake_unverifiable_excerpt() -> dict[str, Any]:
    # Adversarial: the model claims a verified user_stated excerpt that is not in the
    # source. The harness must downgrade provenance and finalize evidence_status
    # (Decision D6); this value must not survive to the ledger.
    data = _valid_intake()
    data["assumptions"][0]["source_excerpt"] = "This text does not appear in the source."
    data["assumptions"][0]["evidence_status"] = "verified_user_stated"
    return data


RESPONSES.update(
    {
        MockScenario.INTAKE_VALID: _raw_json(_valid_intake()),
        MockScenario.INTAKE_DURABLE_ID: _raw_json(_intake_durable_id()),
        MockScenario.INTAKE_HIGH_NOT_BLOCKING: _raw_json(_intake_high_not_blocking()),
        MockScenario.INTAKE_DQ_WITHOUT_SOURCE: _raw_json(_intake_dq_without_source()),
        MockScenario.INTAKE_INVALID_ENUM: _raw_json(_intake_invalid_enum()),
        MockScenario.INTAKE_BAD_SESSION_FRAME: _raw_json(_intake_bad_session_frame()),
        MockScenario.INTAKE_UNVERIFIABLE_EXCERPT: _raw_json(_intake_unverifiable_excerpt()),
    }
)


def _blind_spot_audit(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "findings": findings,
        "missing_provenance": [],
        "invalid_source_excerpts": [],
        "unresolved_material_work": [],
        "artifact_blockers": [],
    }


def _audit_work_item(
    *,
    category: str,
    question: str,
    severity: str = "high",
    blocks_closure: bool = True,
    blocking_reason: str | None = None,
) -> dict[str, Any]:
    work_item = {
        "kind": "clarify",
        "question": question,
        "why_it_matters": "The finding affects protocol closure.",
        "what_breaks_if_wrong": "The artifact may hide an unresolved implementation premise.",
        "blast_radius": severity,
        "blocks_closure": blocks_closure,
        "gap_type": "blind_spot",
        "related_refs": ["A-0001"],
        "source_assumption_refs": ["A-0001"],
        "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
    }
    if blocking_reason is not None:
        work_item["blocking_reason"] = blocking_reason
    return {
        "category": category,
        "refs": ["A-0001"],
        "severity": severity,
        "description": question,
        "conversion_target": "work_item",
        "blocks_closure": blocks_closure,
        "work_item": work_item,
    }


def _blind_spot_external_validation() -> dict[str, Any]:
    return {
        "category": "external_validation_needed",
        "refs": ["A-0001"],
        "severity": "high",
        "description": "Processor retry guarantees require external validation.",
        "conversion_target": "assumption",
        "assumption": {
            "statement": "Processor retry guarantees require external validation.",
            "status": "candidate",
            "source_type": "external_required",
            "source_excerpt": None,
            "blast_radius": "high",
            "downstream_impact": "Payment retry correctness",
            "risk_if_wrong": "Retries may duplicate or drop payments.",
            "evidence_status": "external_validation_required",
            "external_fact": "Processor retry contract",
            "depends_on": ["A-0001"],
        },
    }


def _blind_spot_undecidable() -> dict[str, Any]:
    return {
        "category": "undecidable_issue",
        "refs": ["A-0001"],
        "severity": "medium",
        "description": "Current session cannot decide retry ordering under partition.",
        "conversion_target": "assumption",
        "assumption": {
            "statement": "Retry ordering under partition is undecidable in the current session.",
            "status": "candidate",
            "source_type": "model_inferred",
            "source_excerpt": None,
            "blast_radius": "medium",
            "downstream_impact": "Failure-mode design",
            "risk_if_wrong": "Partition behavior may be implemented incorrectly.",
            "evidence_status": "undecidable",
            "depends_on": ["A-0001"],
        },
    }


def _blind_spot_contradiction() -> dict[str, Any]:
    return {
        "category": "contradiction",
        "refs": ["A-0001", "A-0002"],
        "severity": "high",
        "description": "Retry ownership and payment-write ownership conflict.",
        "conversion_target": "contradiction",
        "contradiction": {
            "refs": ["A-0001", "A-0002"],
            "severity": "high",
            "description": "Retry ownership and payment-write ownership conflict.",
            "status": "open",
        },
    }


def _blind_spot_covered() -> dict[str, Any]:
    return {
        "category": "authority_confusion",
        "refs": ["A-0001"],
        "severity": "low",
        "description": "Authority issue is already represented.",
        "conversion_target": "no_op",
        "covered_by": ["A-0001"],
    }


def _blind_spot_durable_id() -> dict[str, Any]:
    finding = _audit_work_item(
        category="authority_confusion",
        question="Who owns payment retry authority?",
    )
    finding["work_item"]["id"] = "W-9999"
    return finding


def _blind_spot_missing_conversion() -> dict[str, Any]:
    return {
        "category": "authority_confusion",
        "refs": ["A-0001"],
        "severity": "high",
        "description": "Authority is unresolved but not converted.",
        "conversion_target": "work_item",
        "blocks_closure": True,
    }


RESPONSES.update(
    {
        MockScenario.BLIND_SPOT_AUDIT_NO_FINDINGS: _raw_json(_blind_spot_audit([])),
        MockScenario.BLIND_SPOT_AUDIT_AUTHORITY_CONFUSION: _raw_json(
            _blind_spot_audit(
                [
                    _audit_work_item(
                        category="authority_confusion",
                        question="Who is authoritative for retry ledger state?",
                    )
                ]
            )
        ),
        MockScenario.BLIND_SPOT_AUDIT_FAILURE_PATH: _raw_json(
            _blind_spot_audit(
                [
                    _audit_work_item(
                        category="failure_behavior_omission",
                        question="What happens when retry persistence fails?",
                    )
                ]
            )
        ),
        MockScenario.BLIND_SPOT_AUDIT_EXTERNAL_VALIDATION: _raw_json(
            _blind_spot_audit([_blind_spot_external_validation()])
        ),
        MockScenario.BLIND_SPOT_AUDIT_UNDECIDABLE: _raw_json(
            _blind_spot_audit([_blind_spot_undecidable()])
        ),
        MockScenario.BLIND_SPOT_AUDIT_CONTRADICTION: _raw_json(
            _blind_spot_audit([_blind_spot_contradiction()])
        ),
        MockScenario.BLIND_SPOT_AUDIT_COVERED: _raw_json(
            _blind_spot_audit([_blind_spot_covered()])
        ),
        MockScenario.BLIND_SPOT_AUDIT_HIGH_NONBLOCKING: _raw_json(
            _blind_spot_audit(
                [
                    _audit_work_item(
                        category="authority_confusion",
                        question="Who owns payment retry authority?",
                        severity="high",
                        blocks_closure=False,
                    )
                ]
            )
        ),
        MockScenario.BLIND_SPOT_AUDIT_MEDIUM_BLOCKING_NO_REASON: _raw_json(
            _blind_spot_audit(
                [
                    _audit_work_item(
                        category="failure_behavior_omission",
                        question="What happens if retry reconciliation fails?",
                        severity="medium",
                        blocks_closure=True,
                    )
                ]
            )
        ),
        MockScenario.BLIND_SPOT_AUDIT_LOW_BLOCKING: _raw_json(
            _blind_spot_audit(
                [
                    _audit_work_item(
                        category="human_override_path",
                        question="Who can override retry warnings?",
                        severity="low",
                        blocks_closure=True,
                        blocking_reason="Low work must not block closure.",
                    )
                ]
            )
        ),
        MockScenario.BLIND_SPOT_AUDIT_NONEXISTENT_COVERED: _raw_json(
            _blind_spot_audit(
                [
                    {
                        **_blind_spot_covered(),
                        "covered_by": ["A-9999"],
                    }
                ]
            )
        ),
        MockScenario.BLIND_SPOT_AUDIT_DURABLE_ID: _raw_json(
            _blind_spot_audit([_blind_spot_durable_id()])
        ),
        MockScenario.BLIND_SPOT_AUDIT_MISSING_CONVERSION: _raw_json(
            _blind_spot_audit([_blind_spot_missing_conversion()])
        ),
    }
)


DEFAULT_SCENARIO_BY_JOB: dict[ModelJob, MockScenario] = {
    ModelJob.INITIAL_EXTRACTION: MockScenario.INITIAL_EXTRACTION,
    ModelJob.INTAKE_UNSTRUCTURED_INPUT: MockScenario.INTAKE_VALID,
    ModelJob.RANK_NEXT_WORK_ITEM: MockScenario.RANK_NEXT_WORK_ITEM,
    ModelJob.INTERPRET_USER_ANSWER: MockScenario.INTERPRET_CONFIRM,
    ModelJob.CONTRADICTION_AUDIT: MockScenario.CONTRADICTION_AUDIT,
    ModelJob.BLIND_SPOT_AUDIT: MockScenario.BLIND_SPOT_AUDIT_NO_FINDINGS,
    ModelJob.ARTIFACT_GENERATION: MockScenario.ARTIFACT_GENERATION,
}


class DeterministicMockModel(ModelAdapter):
    """Scripted model adapter with no network dependency."""

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        resolved = self._resolve_scenario(request, scenario)
        if resolved == MockScenario.INTERPRET_CONFIRM:
            return _with_v2_revision_required(request, _interpret_confirm_response(request))
        return _with_v2_revision_required(request, RESPONSES[resolved])

    def _resolve_scenario(
        self, request: ModelRequest, scenario: str | None
    ) -> MockScenario:
        if scenario is not None:
            return MockScenario(scenario)
        if request.job == ModelJob.INTERPRET_USER_ANSWER:
            answer_class = request.payload.get("answer_class")
            if answer_class is not None:
                candidate = f"{ModelJob.INTERPRET_USER_ANSWER.value}:{answer_class}"
                if candidate in {item.value for item in MockScenario}:
                    return MockScenario(candidate)
        return DEFAULT_SCENARIO_BY_JOB[request.job]


DEFAULT_MODEL_ADAPTER: ModelAdapter = DeterministicMockModel()


def _interpret_confirm_response(request: ModelRequest) -> str:
    active = request.payload.get("active_work_item")
    projection = request.payload.get("projection")
    target = _mapping_get(active, "target_entity") or "A-0001"
    work_item_id = _mapping_get(active, "id") or "W-0001"
    assumption = _find_projection_item(projection, "assumptions", target)
    work_item = _find_projection_item(projection, "work_items", work_item_id)
    assumption_from = _mapping_get(assumption, "status") or "provisional"
    work_from = _mapping_get(work_item, "status") or _mapping_get(active, "status") or "active"
    return _raw_json(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": target,
                    "payload": {
                        "from": assumption_from,
                        "to": "locked",
                        "reason": "User confirmed the active assumption.",
                    },
                },
                {
                    "event_type": "WORK_ITEM_STATUS_CHANGED",
                    "target_ref": work_item_id,
                    "payload": {
                        "from": work_from,
                        "to": "answered",
                        "reason": "Answer interpreted as confirm.",
                    },
                },
            ],
            "followup_required": False,
            "warnings": [],
        }
    )


def _mapping_get(value, key: str):
    return value.get(key) if hasattr(value, "get") else None


def _find_projection_item(projection, collection: str, ident: str):
    items = _mapping_get(projection, collection) or ()
    for item in items:
        if _mapping_get(item, "id") == ident:
            return item
    return None


def _with_v2_revision_required(request: ModelRequest, raw: str) -> str:
    if request.job != ModelJob.INTERPRET_USER_ANSWER:
        return raw
    projection = request.payload.get("projection")
    if _mapping_get(projection, "protocol_version") != "2.0.0":
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict) and "revision_required" not in parsed:
        parsed["revision_required"] = False
        return _raw_json(parsed)
    return raw
