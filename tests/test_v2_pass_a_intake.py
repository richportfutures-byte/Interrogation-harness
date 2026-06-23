"""V2 Pass A: intake layer (jobs, routing, validator, run-intake, ask-next block)."""

from __future__ import annotations

import pytest

from interrogation_harness.interrogation import OperationError
from interrogation_harness.model import DeterministicMockModel, MockScenario
from interrogation_harness.model.adapter import (
    SHARED_JOBS,
    V1_JOBS,
    V2_JOBS,
    ModelJob,
)
from interrogation_harness.model.jobs import audit_job, extraction_job, job_spec
from interrogation_harness.operations import HarnessOperations

TS = "2026-01-01T00:00:00Z"
SOURCE = "Payments require idempotency keys.\n"


class _ScenarioModel:
    """Deterministic adapter that always returns one named scenario's raw output."""

    def __init__(self, scenario: MockScenario) -> None:
        self._scenario = scenario
        self._mock = DeterministicMockModel()

    def complete(self, request, *, scenario=None):
        return self._mock.complete(request, scenario=self._scenario.value)


def _ops(tmp_path, session_id="v2_pass_a", *, scenario: MockScenario | None = None):
    model = _ScenarioModel(scenario) if scenario is not None else DeterministicMockModel()
    return HarnessOperations(tmp_path / "sessions", session_id, model=model, now=lambda: TS)


def _types(ops):
    return [event["event_type"] for event in ops.event_log.read_events()]


# -- 1-4: job registration, permissions, protocol routing ------------------


def test_v2_job_names_registered_and_distinct():
    assert ModelJob("intake_unstructured_input") is ModelJob.INTAKE_UNSTRUCTURED_INPUT
    assert ModelJob("blind_spot_audit") is ModelJob.BLIND_SPOT_AUDIT
    assert V1_JOBS.isdisjoint(V2_JOBS)
    assert V2_JOBS.isdisjoint(SHARED_JOBS)
    assert ModelJob.INTAKE_UNSTRUCTURED_INPUT in V2_JOBS
    assert ModelJob.BLIND_SPOT_AUDIT in V2_JOBS


def test_job_permission_metadata_matches_spec():
    assert job_spec(ModelJob.INITIAL_EXTRACTION).may_create is True
    assert job_spec(ModelJob.INTAKE_UNSTRUCTURED_INPUT).may_create is True
    assert job_spec(ModelJob.INTERPRET_USER_ANSWER).may_create is True
    assert job_spec(ModelJob.RANK_NEXT_WORK_ITEM).may_create is False
    assert job_spec(ModelJob.RANK_NEXT_WORK_ITEM).allowed_event_types == frozenset()
    assert job_spec(ModelJob.CONTRADICTION_AUDIT).may_create is False
    assert job_spec(ModelJob.BLIND_SPOT_AUDIT).may_create is False
    assert job_spec(ModelJob.ARTIFACT_GENERATION).may_create is False
    assert (
        job_spec(ModelJob.INTAKE_UNSTRUCTURED_INPUT).allowed_event_types
        == job_spec(ModelJob.INITIAL_EXTRACTION).allowed_event_types
    )


def test_protocol_routing_v1():
    assert extraction_job("1.0.0") is ModelJob.INITIAL_EXTRACTION
    assert audit_job("1.0.0") is ModelJob.CONTRADICTION_AUDIT


def test_protocol_routing_v2():
    assert extraction_job("2.0.0") is ModelJob.INTAKE_UNSTRUCTURED_INPUT
    assert audit_job("2.0.0") is ModelJob.BLIND_SPOT_AUDIT


# -- 5-6: V1 unchanged and not silently upgraded ---------------------------


def test_v1_extraction_and_no_upgrade(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    ops.add_source(SOURCE)
    result = ops.run_initial_extraction()
    assert result.accepted
    ledger = ops.ledger()
    assert [a["id"] for a in ledger["assumptions"]]  # V1 extraction created entities
    assert "protocol_version" not in ledger  # still V1
    # add-source, ask-next, run-audit do not upgrade.
    ops.ask_next()
    ops.run_audit()
    assert "protocol_version" not in ops.ledger()


def test_run_intake_without_flag_refuses_and_does_not_upgrade(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    ops.add_source(SOURCE)
    with pytest.raises(OperationError):
        ops.run_intake()
    assert "protocol_version" not in ops.ledger()


# -- 7: explicit upgrade ----------------------------------------------------


def test_upgrade_to_v2_via_intake(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()  # V1
    ops.add_source(SOURCE)
    result = ops.run_intake(upgrade_to_v2=True)
    assert result.accepted
    ledger = ops.ledger()
    assert ledger["protocol_version"] == "2.0.0"
    assert ledger["intake_status"] == "complete"
    assert "ASSUMPTION_CREATED" in _types(ops)


# -- 8: ask-next intake block ----------------------------------------------


def test_v2_required_intake_blocks_ask_next(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)
    assert ops.ledger()["intake_status"] == "required"
    with pytest.raises(OperationError):
        ops.ask_next()


# -- 9-11: accepted intake outcomes ----------------------------------------


def test_accepted_intake_creates_entities_with_minted_ids(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)
    result = ops.run_intake()
    assert result.accepted
    ledger = ops.ledger()
    assert [a["id"] for a in ledger["assumptions"]] == ["A-0001", "A-0002"]
    first = ledger["assumptions"][0]
    assert first["intake_label"] == "CA-01"
    assert first["premise_origin"] == "intake"
    assert first["source_type"] == "user_stated"
    assert first["source_excerpt_verified"] is True
    work_item = ledger["work_items"][0]
    assert work_item["id"] == "W-0001"
    assert work_item["derived_question_label"] == "DQ-01"
    assert work_item["gap_type"] == "failure_mode"
    assert work_item["source_assumption_ids"] == ["A-0001"]
    created = next(e for e in ops.event_log.read_events() if e["event_type"] == "ASSUMPTION_CREATED")
    assert created["ref_map"] == {"tmp_assumption_1": "A-0001"}


def test_accepted_intake_projects_complete(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)
    ops.run_intake()
    assert ops.ledger()["intake_status"] == "complete"


def test_session_frame_stored_on_accepted_model_response(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)
    ops.run_intake()
    accepted = [
        e
        for e in ops.event_log.read_events()
        if e["event_type"] == "MODEL_RESPONSE_RECORDED" and e["payload"].get("accepted")
    ]
    assert accepted
    frame = accepted[0]["payload"]["session_frame"]
    assert frame["input_mode"] == "unstructured"
    assert frame["topic"] == "payment retries"
    assert ops.ledger()["session_frame"]["input_mode"] == "unstructured"


# -- 12-16: rejection scenarios (no mutation) ------------------------------


def _run_rejected_intake(tmp_path, scenario, *, source=SOURCE):
    ops = _ops(tmp_path, scenario=scenario)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(source)
    result = ops.run_intake()
    return ops, result


def test_dq_without_source_rejected(tmp_path):
    ops, result = _run_rejected_intake(tmp_path, MockScenario.INTAKE_DQ_WITHOUT_SOURCE)
    assert not result.accepted
    assert ops.ledger()["assumptions"] == []
    assert "PROPOSAL_REJECTED" in _types(ops)


def test_high_blast_not_blocking_rejected(tmp_path):
    ops, result = _run_rejected_intake(tmp_path, MockScenario.INTAKE_HIGH_NOT_BLOCKING)
    assert not result.accepted
    assert ops.ledger()["assumptions"] == []
    assert "PROPOSAL_REJECTED" in _types(ops)


def test_durable_id_in_creation_rejected(tmp_path):
    ops, result = _run_rejected_intake(tmp_path, MockScenario.INTAKE_DURABLE_ID)
    assert not result.accepted
    assert ops.ledger()["assumptions"] == []
    rejected_model = [
        e
        for e in ops.event_log.read_events()
        if e["event_type"] == "MODEL_RESPONSE_RECORDED" and e["payload"].get("accepted") is False
    ]
    assert rejected_model


def test_invalid_v2_enum_rejected(tmp_path):
    ops, result = _run_rejected_intake(tmp_path, MockScenario.INTAKE_INVALID_ENUM)
    assert not result.accepted
    assert ops.ledger()["assumptions"] == []


def test_bad_session_frame_rejected(tmp_path):
    ops, result = _run_rejected_intake(tmp_path, MockScenario.INTAKE_BAD_SESSION_FRAME)
    assert not result.accepted
    assert ops.ledger()["assumptions"] == []
    # No upgrade either, since no accepted intake occurred.
    assert ops.ledger()["protocol_version"] == "2.0.0"  # explicit create still V2


# -- 17: provenance downgrade, not dropped ---------------------------------


def test_unverifiable_user_stated_excerpt_downgraded_not_dropped(tmp_path):
    ops = _ops(tmp_path, scenario=MockScenario.INTAKE_UNVERIFIABLE_EXCERPT)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source("Some unrelated project notes with no matching excerpt.\n")
    result = ops.run_intake()
    assert result.accepted
    ledger = ops.ledger()
    assert len(ledger["assumptions"]) == 2  # not dropped
    first = ledger["assumptions"][0]
    assert first["source_type"] == "model_inferred"  # downgraded
    assert first["source_excerpt_verified"] is False
