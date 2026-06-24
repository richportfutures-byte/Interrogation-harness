"""V2 Pass D: blind-spot audit conversion and closure gate."""

from __future__ import annotations

import pytest

from interrogation_harness import canonical
from interrogation_harness.events import EventType
from interrogation_harness.interrogation import OperationError
from interrogation_harness.model import DeterministicMockModel
from interrogation_harness.model.adapter import ModelJob
from interrogation_harness.operations import HarnessOperations

TS = "2026-01-01T00:00:00Z"
SOURCE = "Payments require idempotency keys.\n"


class _OverrideModel:
    """Delegate to the deterministic mock except for explicitly supplied jobs."""

    def __init__(
        self,
        *,
        audit_raw: str | None = None,
        rank_raw: str | None = None,
        answer_raw: str | None = None,
    ) -> None:
        self.audit_raw = audit_raw
        self.rank_raw = rank_raw
        self.answer_raw = answer_raw
        self.default = DeterministicMockModel()

    def complete(self, request, *, scenario=None):
        if request.job == ModelJob.BLIND_SPOT_AUDIT and self.audit_raw is not None:
            return self.audit_raw
        if request.job == ModelJob.RANK_NEXT_WORK_ITEM and self.rank_raw is not None:
            return self.rank_raw
        if request.job == ModelJob.INTERPRET_USER_ANSWER and self.answer_raw is not None:
            return self.answer_raw
        return self.default.complete(request, scenario=scenario)


def _raw(obj: dict) -> str:
    return canonical.dumps_event_line(obj)


def _audit(findings: list[dict]) -> str:
    return _raw(
        {
            "findings": findings,
            "missing_provenance": [],
            "invalid_source_excerpts": [],
            "unresolved_material_work": [],
            "artifact_blockers": [],
        }
    )


def _work_finding(
    *,
    category: str = "authority_confusion",
    question: str = "Who owns payment retry authority?",
    severity: str = "high",
    blocks_closure: bool = True,
    blocking_reason: str | None = None,
    gap_type: str | None = None,
) -> dict:
    work_item = {
        "kind": "clarify",
        "question": question,
        "why_it_matters": "It controls whether the artifact can close safely.",
        "what_breaks_if_wrong": "The downstream build may rely on hidden authority.",
        "blast_radius": severity,
        "blocks_closure": blocks_closure,
        "related_refs": ["A-0001"],
        "source_assumption_refs": ["A-0001"],
        "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
    }
    if gap_type is not None:
        work_item["gap_type"] = gap_type
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


def _assumption_finding(
    *,
    category: str,
    statement: str,
    source_type: str = "model_inferred",
    evidence_status: str = "model_inferred",
    blast_radius: str = "medium",
    external_fact: str | None = None,
) -> dict:
    assumption = {
        "statement": statement,
        "status": "candidate",
        "source_type": source_type,
        "source_excerpt": None,
        "blast_radius": blast_radius,
        "downstream_impact": "Closure correctness",
        "risk_if_wrong": "The artifact can hide an unresolved premise.",
        "evidence_status": evidence_status,
        "depends_on": ["A-0001"],
    }
    if external_fact is not None:
        assumption["external_fact"] = external_fact
    return {
        "category": category,
        "refs": ["A-0001"],
        "severity": blast_radius,
        "description": statement,
        "conversion_target": "assumption",
        "assumption": assumption,
    }


def _contradiction_finding() -> dict:
    return {
        "category": "contradiction",
        "refs": ["A-0001", "A-0002"],
        "severity": "high",
        "description": "Retry authority conflicts with payment write authority.",
        "conversion_target": "contradiction",
        "contradiction": {
            "refs": ["A-0001", "A-0002"],
            "severity": "high",
            "description": "Retry authority conflicts with payment write authority.",
            "status": "open",
        },
    }


def _covered_finding(ref: str = "A-0001") -> dict:
    return {
        "category": "authority_confusion",
        "refs": ["A-0001"],
        "severity": "low",
        "description": "Already represented authority concern.",
        "conversion_target": "no_op",
        "covered_by": [ref],
    }


def _rank(selected: str, *, tested: str | None = "A-0001") -> str:
    return _raw(
        {
            "selected_work_item_id": selected,
            "question": "Resolve the audit-created blocker?",
            "why_it_matters": "It controls protocol closure.",
            "what_breaks_if_wrong": "The artifact may hide unresolved work.",
            "tested_entity_id": tested,
            "recommended_default": None,
            "recommended_default_basis": None,
            "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
        }
    )


def _answer_work_only(work_item_id: str) -> str:
    return _raw(
        {
            "proposed_events": [
                {
                    "event_type": "WORK_ITEM_STATUS_CHANGED",
                    "target_ref": work_item_id,
                    "payload": {
                        "from": "active",
                        "to": "answered",
                        "reason": "Audit-created work was answered.",
                    },
                }
            ],
            "followup_required": False,
            "revision_required": False,
            "warnings": [],
        }
    )


def _ops(tmp_path, *, audit_raw: str | None = None, session_id: str = "v2_pass_d"):
    return HarnessOperations(
        tmp_path / "sessions",
        session_id,
        model=_OverrideModel(audit_raw=audit_raw),
        now=lambda: TS,
    )


def _v2_intake(tmp_path, *, audit_raw: str | None = None, session_id: str = "v2_pass_d"):
    ops = _ops(tmp_path, audit_raw=audit_raw, session_id=session_id)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)
    result = ops.run_intake()
    assert result.accepted
    return ops


def _v2_resolved_intake(
    tmp_path, *, audit_raw: str | None = None, session_id: str = "v2_pass_d"
):
    ops = _v2_intake(tmp_path, audit_raw=audit_raw, session_id=session_id)
    ops.ask_next()
    result = ops.answer("confirm")
    assert result.accepted
    assert all(item["status"] != "active" for item in ops.ledger()["work_items"])
    return ops


def _events(ops: HarnessOperations, event_type: str) -> list[dict]:
    return [event for event in ops.event_log.read_events() if event["event_type"] == event_type]


def test_v1_run_audit_remains_contradiction_audit_without_v2_fields(tmp_path):
    ops = HarnessOperations(tmp_path / "sessions", "v1_audit", now=lambda: TS)
    ops.create_session()
    ops.add_source(SOURCE)
    assert ops.run_initial_extraction().accepted

    result = ops.run_audit()

    assert result["accepted"] is True
    audit_event = _events(ops, EventType.AUDIT_RUN.value)[-1]
    assert "audit_type" not in audit_event["payload"]
    model_event = _events(ops, EventType.MODEL_RESPONSE_RECORDED.value)[-1]
    assert model_event["payload"]["job"] == "contradiction_audit"
    assert "protocol_version" not in ops.ledger()


def test_v2_run_audit_aliases_blind_spot_audit(tmp_path):
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([]), session_id="v2_alias")

    result = ops.run_audit()

    assert result["accepted"] is True
    audit_event = _events(ops, EventType.AUDIT_RUN.value)[-1]
    assert audit_event["payload"]["audit_type"] == "blind_spot"
    model_event = _events(ops, EventType.MODEL_RESPONSE_RECORDED.value)[-1]
    assert model_event["payload"]["job"] == "blind_spot_audit"
    assert ops.ledger()["blind_spot_audit_status"] == "complete"


def test_v2_blind_spot_audit_requires_completed_intake(tmp_path):
    ops = _ops(tmp_path, audit_raw=_audit([]), session_id="audit_before_intake")
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)

    with pytest.raises(OperationError, match="completed V2 intake"):
        ops.run_blind_spot_audit()


def test_v2_blind_spot_audit_rejects_active_work(tmp_path):
    ops = _v2_intake(tmp_path, audit_raw=_audit([]), session_id="audit_active")
    ops.ask_next()

    with pytest.raises(OperationError, match="no active work items"):
        ops.run_blind_spot_audit()

    assert not _events(ops, EventType.AUDIT_RUN.value)


def test_v2_blind_spot_audit_no_findings_marks_complete(tmp_path):
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([]), session_id="no_findings")

    result = ops.run_blind_spot_audit()

    assert result["accepted"] is True
    assert ops.ledger()["blind_spot_audit_status"] == "complete"
    assert len(ops.ledger()["work_items"]) == 1


def test_authority_confusion_creates_blocking_work(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding(category="authority_confusion")]),
        session_id="authority_confusion",
    )

    assert ops.run_blind_spot_audit()["accepted"] is True
    created = ops.ledger()["work_items"][-1]

    assert created["blocks_closure"] is True
    assert created["blast_radius"] == "high"
    assert created["gap_type"] == "authority_ownership"
    assert created["source_assumption_ids"] == ["A-0001"]


def test_failure_path_omission_creates_blocking_work(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit(
            [
                _work_finding(
                    category="failure_behavior_omission",
                    question="What happens if retry persistence fails?",
                )
            ]
        ),
        session_id="failure_path",
    )

    ops.run_blind_spot_audit()
    created = ops.ledger()["work_items"][-1]

    assert created["blocks_closure"] is True
    assert created["gap_type"] == "failure_mode"


def test_external_validation_material_is_recorded_as_assumption(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit(
            [
                _assumption_finding(
                    category="external_validation_needed",
                    statement="Processor retry guarantees require external validation.",
                    source_type="external_required",
                    evidence_status="external_validation_required",
                    blast_radius="high",
                    external_fact="Processor retry guarantee",
                )
            ]
        ),
        session_id="external_validation",
    )

    ops.run_blind_spot_audit()
    created = ops.ledger()["assumptions"][-1]

    assert created["premise_origin"] == "blind_spot"
    assert created["source_type"] == "external_required"
    assert created["evidence_status"] == "external_validation_required"


def test_undecidable_material_is_recorded_on_assumption(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit(
            [
                _assumption_finding(
                    category="undecidable_issue",
                    statement="Partition retry ordering is undecidable in this session.",
                    evidence_status="undecidable",
                )
            ]
        ),
        session_id="undecidable",
    )

    ops.run_blind_spot_audit()
    created = ops.ledger()["assumptions"][-1]

    assert created["premise_origin"] == "blind_spot"
    assert created["evidence_status"] == "undecidable"


def test_contradiction_finding_creates_contradiction_and_resolution_work(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_contradiction_finding()]),
        session_id="contradiction",
    )

    ops.run_blind_spot_audit()
    contradiction = ops.ledger()["contradictions"][-1]
    work = ops.ledger()["work_items"][-1]

    assert contradiction["status"] == "open"
    assert contradiction["resolution_work_item"] == work["id"]
    assert work["kind"] == "resolve_contradiction"
    assert work["blocks_closure"] is True


def test_covered_noop_finding_validates_without_new_records(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_covered_finding()]),
        session_id="covered",
    )
    before = {key: len(ops.ledger()[key]) for key in ("assumptions", "work_items", "risks", "contradictions")}

    result = ops.run_blind_spot_audit()
    after = {key: len(ops.ledger()[key]) for key in before}

    assert result["accepted"] is True
    assert after == before
    assert ops.ledger()["blind_spot_audit_status"] == "complete"


def test_high_nonblocking_audit_work_is_rejected(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding(severity="high", blocks_closure=False)]),
        session_id="high_nonblocking",
    )

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "high blast radius" in result["errors"][0]
    assert ops.ledger()["blind_spot_audit_status"] == "not_run"


def test_medium_blocking_without_reason_is_rejected(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding(severity="medium", blocks_closure=True)]),
        session_id="medium_no_reason",
    )

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "blocking_reason" in result["errors"][0]


def test_low_blocking_audit_work_is_rejected(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit(
            [
                _work_finding(
                    severity="low",
                    blocks_closure=True,
                    blocking_reason="Low work cannot block closure.",
                )
            ]
        ),
        session_id="low_blocking",
    )

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "low blast radius" in result["errors"][0]


def test_nonexistent_linked_refs_are_rejected(tmp_path):
    bad = _work_finding()
    bad["refs"] = ["A-9999"]
    bad["work_item"]["related_refs"] = ["A-9999"]
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([bad]), session_id="bad_refs")

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "does not exist" in result["errors"][0]


def test_noop_citing_nonexistent_covered_record_is_rejected(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_covered_finding("A-9999")]),
        session_id="bad_covered",
    )

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "covered record" in result["errors"][0]


def test_durable_ids_inside_creation_payloads_are_rejected(tmp_path):
    bad = _work_finding()
    bad["work_item"]["id"] = "W-9999"
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([bad]), session_id="durable_id")

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "identity" in result["errors"][0] or "unknown fields" in result["errors"][0]


def test_invalid_evidence_status_combinations_are_rejected(tmp_path):
    bad = _assumption_finding(
        category="undecidable_issue",
        statement="The model cannot verify itself.",
        source_type="model_inferred",
        evidence_status="verified_user_stated",
    )
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([bad]), session_id="bad_evidence")

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "model_inferred" in result["errors"][0]


def test_material_finding_missing_conversion_payload_is_rejected(tmp_path):
    bad = {
        "category": "authority_confusion",
        "refs": ["A-0001"],
        "severity": "high",
        "description": "Authority is unresolved but not converted.",
        "conversion_target": "work_item",
        "blocks_closure": True,
    }
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([bad]), session_id="missing_conversion")

    result = ops.run_blind_spot_audit()

    assert not result["accepted"]
    assert "work_item" in result["errors"][0]


def test_v2_normal_artifact_requires_blind_spot_audit(tmp_path):
    ops = _v2_resolved_intake(tmp_path, audit_raw=_audit([]), session_id="artifact_no_audit")

    with pytest.raises(OperationError, match="blind-spot audit"):
        ops.generate_artifact()


def test_v2_normal_artifact_rejects_unresolved_closure_blockers(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="artifact_blocker",
    )
    ops.run_blind_spot_audit()

    with pytest.raises(OperationError, match="closure blockers"):
        ops.generate_artifact()


def test_v2_normal_artifact_allows_nonblocking_unresolved_work(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit(
            [
                _work_finding(
                    category="human_override_path",
                    question="Who receives low-impact retry notifications?",
                    severity="low",
                    blocks_closure=False,
                )
            ]
        ),
        session_id="artifact_nonblocking",
    )
    ops.run_blind_spot_audit()

    result = ops.generate_artifact()

    assert result["accepted"] is True
    assert ops.ledger()["work_items"][-1]["status"] == "open"
    artifact_event = _events(ops, EventType.ARTIFACT_GENERATED.value)[-1]
    assert artifact_event["payload"]["closure_status"]["complete"] is True


def test_v2_normal_artifact_rejects_active_work(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit(
            [
                _work_finding(
                    category="human_override_path",
                    question="Who receives low-impact retry notifications?",
                    severity="low",
                    blocks_closure=False,
                )
            ]
        ),
        session_id="artifact_active",
    )
    ops.run_blind_spot_audit()
    ops.model = _OverrideModel(audit_raw=_audit([]), rank_raw=_rank("W-0002"))
    ops.ask_next()

    with pytest.raises(OperationError, match="active work"):
        ops.generate_artifact()


def test_v2_force_close_preserves_unresolved_blockers(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="force_preserves",
    )
    ops.run_blind_spot_audit()

    ledger = ops.force_close(reason="controlled incomplete closure")

    blocker = next(item for item in ledger["work_items"] if item["id"] == "W-0002")
    assert ledger["force_closed"] is True
    assert blocker["status"] == "open"
    assert blocker["blocks_closure"] is True


def test_v2_force_close_artifact_marks_incomplete_closure(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="force_incomplete",
    )
    ops.run_blind_spot_audit()
    ops.force_close(reason="controlled incomplete closure")

    result = ops.generate_artifact()
    artifact_event = _events(ops, EventType.ARTIFACT_GENERATED.value)[-1]

    assert result["accepted"] is True
    assert artifact_event["payload"]["closure_status"]["mode"] == "force_closed"
    assert artifact_event["payload"]["closure_status"]["complete"] is False
    assert "Unresolved closure-blocking work remains." in ops.store.artifact_path.read_text(
        encoding="utf-8"
    )


def test_force_close_does_not_hide_blockers_on_success_path(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="force_no_hide",
    )
    ops.run_blind_spot_audit()
    with pytest.raises(OperationError, match="closure blockers"):
        ops.generate_artifact()

    ops.force_close(reason="controlled incomplete closure")
    ops.generate_artifact()
    artifact_event = _events(ops, EventType.ARTIFACT_GENERATED.value)[-1]

    assert artifact_event["payload"]["closure_status"]["complete"] is False
    assert any(item["id"] == "W-0002" and item["status"] == "open" for item in ops.ledger()["work_items"])


def test_failed_artifact_gate_does_not_write_final_v2_artifact(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="artifact_gate",
    )
    ops.run_blind_spot_audit()

    with pytest.raises(OperationError):
        ops.generate_artifact()

    assert not ops.store.artifact_path.exists()


def test_pass_b_ranking_selects_audit_created_blocker(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="rank_audit_blocker",
    )
    ops.run_blind_spot_audit()
    ops.model = _OverrideModel(audit_raw=_audit([]), rank_raw=_rank("W-0002"))

    active = ops.ask_next()

    assert active["id"] == "W-0002"
    assert active["status"] == "active"


def test_pass_c_answer_assimilation_resolves_audit_created_blocker(tmp_path):
    ops = _v2_resolved_intake(
        tmp_path,
        audit_raw=_audit([_work_finding()]),
        session_id="answer_audit_blocker",
    )
    ops.run_blind_spot_audit()
    ops.model = _OverrideModel(
        audit_raw=_audit([]),
        rank_raw=_rank("W-0002"),
        answer_raw=_answer_work_only("W-0002"),
    )
    ops.ask_next()

    result = ops.answer("The retry ledger owner is the billing worker.")

    assert result.accepted
    assert next(item for item in ops.ledger()["work_items"] if item["id"] == "W-0002")[
        "status"
    ] == "resolved"
