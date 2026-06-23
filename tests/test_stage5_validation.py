"""Stage 5 proof: model validation pipeline and job permissions."""

from __future__ import annotations

import copy

from interrogation_harness import canonical
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.model import DeterministicMockModel, MockScenario, ModelJob
from interrogation_harness.projection import LedgerProjector
from interrogation_harness.session_store import SessionStore
from interrogation_harness.validation import ModelContractValidator

TS = "2026-01-01T00:00:00Z"
SID = "sess_stage5"


class ScriptedAdapter:
    """Small test adapter that returns canned raw strings and counts calls."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, request, *, scenario=None):
        self.calls += 1
        output = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        if isinstance(output, Exception):
            raise output
        return output


def _raw(obj):
    return canonical.dumps_event_line(obj)


def _log(tmp_path) -> EventLog:
    store = SessionStore(tmp_path / "sessions", SID)
    store.create()
    return EventLog(store)


def _append(log, event_type, payload, n, *, actor=Actor.HARNESS):
    return log.append(
        event_type=event_type,
        actor=actor,
        session_id=SID,
        correlation_id=f"seed-{n}",
        idempotency_key=f"seed-key-{n}",
        timestamp=TS,
        payload=payload,
    )


def _seed_session(log):
    _append(log, EventType.SESSION_CREATED, {"session_id": SID}, 0)


def _seed_assumption_and_work(log, *, status="provisional", work_status="active"):
    _seed_session(log)
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0001",
            "statement": "Payments require idempotency keys.",
            "status": status,
            "source_type": "user_stated",
            "source_excerpt": "Payments require idempotency keys.",
            "source_excerpt_verified": True,
            "blast_radius": "high",
            "downstream_impact": "payments",
            "risk_if_wrong": "duplicate charges",
        },
        1,
    )
    _append(
        log,
        EventType.WORK_ITEM_CREATED,
        {
            "id": "W-0001",
            "kind": "resolve_assumption",
            "status": work_status,
            "question": "Confirm idempotency?",
            "why_it_matters": "payments",
            "what_breaks_if_wrong": "duplicate charges",
            "blast_radius": "high",
            "blocks_closure": True,
            "target_entity": "A-0001",
            "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
        },
        2,
    )


def _initial_output(*, source_excerpt="Payments require idempotency keys."):
    return {
        "assumptions": [
            {
                "tmp_handle": "tmp_assumption_1",
                "statement": "Payments require idempotency keys.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": source_excerpt,
                "blast_radius": "high",
                "downstream_impact": "Payment retries",
                "risk_if_wrong": "Duplicate charges",
            }
        ],
        "work_items": [],
        "risks": [],
        "terms": [],
        "decisions": [],
        "contradictions": [],
    }


def _validator(log, adapter):
    return ModelContractValidator(log, adapter)


def _run(validator, job, key, **kwargs):
    return validator.run(
        job,
        session_id=SID,
        correlation_id=f"corr-{key}",
        idempotency_key=f"key-{key}",
        timestamp=TS,
        **kwargs,
    )


def _project(log):
    return LedgerProjector().project(log.read_events())


def _event_types(log):
    return [event["event_type"] for event in log.read_events()]


def test_durable_id_in_creation_output_is_rejected(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    result = _run(
        _validator(log, DeterministicMockModel()),
        ModelJob.INITIAL_EXTRACTION,
        "durable",
        source_markdown="source",
        scenario=MockScenario.CREATION_WITH_DURABLE_ID.value,
    )

    assert result.accepted is False
    assert result.attempts == 2
    assert "ASSUMPTION_CREATED" not in _event_types(log)
    recorded = [e for e in log.read_events() if e["event_type"] == "MODEL_RESPONSE_RECORDED"]
    assert len(recorded) == 2
    assert all(e["payload"]["accepted"] is False for e in recorded)
    assert log.accepted_correlation("key-durable") is None


def test_missing_user_stated_excerpt_downgrades_and_keeps_candidate(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    adapter = ScriptedAdapter(_raw(_initial_output(source_excerpt="not in source")))
    result = _run(
        _validator(log, adapter),
        ModelJob.INITIAL_EXTRACTION,
        "downgrade",
        source_markdown="Payments are processed asynchronously.",
    )

    assert result.accepted is True
    assumption = result.ledger["assumptions"][0]
    assert assumption["source_type"] == "model_inferred"
    assert assumption["source_excerpt_verified"] is False
    assert assumption["statement"] == "Payments require idempotency keys."
    created = [e for e in log.read_events() if e["event_type"] == "ASSUMPTION_CREATED"][0]
    assert "provenance_downgrade_reason" in created["payload"]


def test_malformed_json_records_non_mutating_model_response(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    before = _project(log)
    result = _run(
        _validator(log, DeterministicMockModel()),
        ModelJob.INTERPRET_USER_ANSWER,
        "malformed",
        scenario=MockScenario.MALFORMED_JSON.value,
    )
    after = _project(log)

    assert result.accepted is False
    assert result.attempts == 2
    assert after == before
    recorded = [e for e in log.read_events() if e["event_type"] == "MODEL_RESPONSE_RECORDED"]
    assert len(recorded) == 2
    assert all(e["payload"]["accepted"] is False for e in recorded)


def test_transport_failure_records_operation_failed_and_does_not_mutate(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    before = _project(log)
    result = _run(
        _validator(log, ScriptedAdapter(RuntimeError("timeout"))),
        ModelJob.INITIAL_EXTRACTION,
        "transport",
        source_markdown="source",
    )
    after = _project(log)

    assert result.accepted is False
    assert after == before
    assert _event_types(log)[-1] == "OPERATION_FAILED"
    failed = log.read_events()[-1]
    assert failed["payload"]["retryable"] is True
    assert log.accepted_correlation("key-transport") is None


def test_schema_failure_retries_exactly_once_then_halts(tmp_path):
    log = _log(tmp_path)
    _seed_assumption_and_work(log)
    invalid_rank = _raw(
        {
            "selected_work_item_id": "W-0001",
            "question": "q",
            "why_it_matters": "w",
        }
    )
    adapter = ScriptedAdapter(invalid_rank, invalid_rank, _raw({"never": "called"}))
    result = _run(
        _validator(log, adapter),
        ModelJob.RANK_NEXT_WORK_ITEM,
        "schema",
    )

    assert result.accepted is False
    assert result.attempts == 2
    assert adapter.calls == 2
    recorded = [e for e in log.read_events() if e["event_type"] == "MODEL_RESPONSE_RECORDED"]
    assert len(recorded) == 2
    assert "PROPOSAL_REJECTED" not in _event_types(log)


def test_illegal_transition_records_rejection_and_does_not_mutate(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0001",
            "statement": "x",
            "status": "candidate",
            "source_type": "model_inferred",
            "blast_radius": "low",
            "downstream_impact": "d",
            "risk_if_wrong": "r",
        },
        1,
    )
    _append(
        log,
        EventType.ASSUMPTION_TRANSITIONED,
        {"id": "A-0001", "from": "candidate", "to": "rejected", "reason": "no"},
        2,
    )
    before = _project(log)
    result = _run(
        _validator(log, DeterministicMockModel()),
        ModelJob.INTERPRET_USER_ANSWER,
        "illegal",
        scenario=MockScenario.ILLEGAL_TRANSITION.value,
    )
    after = _project(log)

    assert result.accepted is False
    assert after == before
    assert "PROPOSAL_REJECTED" in _event_types(log)
    rejected = [e for e in log.read_events() if e["event_type"] == "PROPOSAL_REJECTED"][0]
    assert "rejected -> locked" in rejected["payload"]["reason"]


def test_unknown_durable_reference_is_rejected(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    output = _raw(
        {
            "proposed_events": [
                {
                    "event_type": "RISK_CREATED",
                    "target_ref": "tmp_risk_1",
                    "payload": {
                        "tmp_handle": "tmp_risk_1",
                        "statement": "Unknown existing assumption.",
                        "severity": "high",
                        "status": "open",
                        "source_refs": ["A-9999"],
                    },
                }
            ],
            "followup_required": False,
            "warnings": [],
        }
    )
    result = _run(
        _validator(log, ScriptedAdapter(output)),
        ModelJob.INTERPRET_USER_ANSWER,
        "unknown-ref",
    )

    assert result.accepted is False
    assert "durable reference does not exist" in result.errors[0]
    assert "RISK_CREATED" not in _event_types(log)
    assert "PROPOSAL_REJECTED" in _event_types(log)


def test_rank_next_work_item_cannot_create_entities(tmp_path):
    log = _log(tmp_path)
    _seed_assumption_and_work(log)
    invalid = _raw(
        {
            "selected_work_item_id": "W-0001",
            "question": "Confirm?",
            "why_it_matters": "payments",
            "what_breaks_if_wrong": "duplicates",
            "tested_entity_id": "A-0001",
            "recommended_default": None,
            "recommended_default_basis": None,
            "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
            "work_items": [{"tmp_handle": "tmp_work_2"}],
        }
    )
    result = _run(
        _validator(log, ScriptedAdapter(invalid)),
        ModelJob.RANK_NEXT_WORK_ITEM,
        "rank-create",
    )

    assert result.accepted is False
    assert any("unknown fields" in error for error in result.errors)
    assert _event_types(log).count("WORK_ITEM_CREATED") == 1


def test_contradiction_audit_cannot_directly_mutate_projection(tmp_path):
    log = _log(tmp_path)
    _seed_assumption_and_work(log)
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0002",
            "statement": "Payments are attempted once.",
            "status": "candidate",
            "source_type": "model_inferred",
            "blast_radius": "medium",
            "downstream_impact": "payments",
            "risk_if_wrong": "missed retry behavior",
        },
        3,
    )
    before = copy.deepcopy(_project(log))
    result = _run(
        _validator(log, DeterministicMockModel()),
        ModelJob.CONTRADICTION_AUDIT,
        "audit",
    )
    after = _project(log)

    assert result.accepted is True
    assert after == before
    assert "AUDIT_RUN" in _event_types(log)
    assert "CONTRADICTION_CREATED" not in _event_types(log)


def test_artifact_generation_cannot_invent_locked_assumptions(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    output = _raw(
        {
            "artifact_markdown": "# Final Artifact\n\n## Locked Assumptions\n\n- Invented locked fact.\n",
            "blocking_warnings": [],
            "open_risk_register": [],
            "traceability_summary": [],
        }
    )
    before = _project(log)
    result = _run(
        _validator(log, ScriptedAdapter(output)),
        ModelJob.ARTIFACT_GENERATION,
        "artifact-invent",
    )
    after = _project(log)

    assert result.accepted is False
    assert after == before
    assert "artifact invents locked assumption" in result.errors[0]
    assert "ARTIFACT_GENERATED" not in _event_types(log)


def test_accepted_valid_output_appends_events_and_rebuilds_projection(tmp_path):
    log = _log(tmp_path)
    _seed_session(log)
    result = _run(
        _validator(log, DeterministicMockModel()),
        ModelJob.INITIAL_EXTRACTION,
        "accepted",
        source_markdown="Payments require idempotency keys.",
    )

    assert result.accepted is True
    assert log.store.ledger_exists()
    assert result.ledger == log.store.read_ledger()
    types = _event_types(log)
    assert types.count("MODEL_RESPONSE_RECORDED") == 1
    assert types.count("ASSUMPTION_CREATED") == 2
    assert types.count("WORK_ITEM_CREATED") == 1
    recorded = [e for e in log.read_events() if e["event_type"] == "MODEL_RESPONSE_RECORDED"][0]
    assert recorded["payload"]["accepted"] is True
    first = result.ledger["assumptions"][0]
    assert first["id"] == "A-0001"
    assert first["source_excerpt_verified"] is True
    work_item = result.ledger["work_items"][0]
    assert work_item["target_entity"] == "A-0001"
