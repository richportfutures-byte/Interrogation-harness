"""V2 Pass B: premise blocker ranking."""

from __future__ import annotations

import pytest

from interrogation_harness import canonical
from interrogation_harness.events import Actor, EventType
from interrogation_harness.interrogation import OperationError
from interrogation_harness.operations import HarnessOperations

TS = "2026-01-01T00:00:00Z"
SOURCE = "Payments require idempotency keys.\n"


class _RawModel:
    """Adapter that always returns one fixed raw output string."""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def complete(self, request, *, scenario=None):
        return self._raw


def _ops(tmp_path, raw: str, *, session_id: str = "v2_pass_b") -> HarnessOperations:
    return HarnessOperations(
        tmp_path / "sessions",
        session_id,
        model=_RawModel(raw),
        now=lambda: TS,
    )


def _rank_output(
    selected: str,
    *,
    tested: str | None = "A-0001",
    recommended_default: str | None = None,
    recommended_default_basis: str | None = None,
) -> str:
    return canonical.dumps_event_line(
        {
            "selected_work_item_id": selected,
            "question": "Confirm the selected premise?",
            "why_it_matters": "It controls implementation correctness.",
            "what_breaks_if_wrong": "The downstream build may rely on a false premise.",
            "tested_entity_id": tested,
            "recommended_default": recommended_default,
            "recommended_default_basis": recommended_default_basis,
            "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
        }
    )


def _append(ops: HarnessOperations, event_type: EventType, payload: dict, n: int) -> None:
    ops.event_log.append(
        event_type=event_type,
        actor=Actor.HARNESS,
        session_id=ops.session_id,
        correlation_id=f"seed-{n}",
        idempotency_key=f"seed-key-{ops.session_id}-{n}",
        timestamp=TS,
        payload=payload,
    )


def _assumption_payload() -> dict:
    return {
        "id": "A-0001",
        "statement": "Payments require idempotency keys.",
        "status": "candidate",
        "source_type": "user_stated",
        "source_excerpt": "Payments require idempotency keys.",
        "source_excerpt_verified": True,
        "blast_radius": "high",
        "downstream_impact": "Payment retries",
        "risk_if_wrong": "Duplicate charges",
    }


def _work_payload(
    ident: str,
    *,
    status: str = "open",
    blast_radius: str = "medium",
    blocks_closure: bool = False,
    blocking_reason: str | None = None,
) -> dict:
    payload = {
        "id": ident,
        "kind": "resolve_assumption",
        "status": status,
        "question": f"Question for {ident}?",
        "why_it_matters": "It controls implementation correctness.",
        "what_breaks_if_wrong": "The downstream build may rely on a false premise.",
        "blast_radius": blast_radius,
        "blocks_closure": blocks_closure,
        "target_entity": "A-0001",
        "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
    }
    if blocking_reason is not None:
        payload["blocking_reason"] = blocking_reason
    return payload


def _seed_rank_session(
    tmp_path,
    raw: str,
    *work_items: dict,
    protocol_version: str = "2.0.0",
    session_id: str = "rank_session",
) -> HarnessOperations:
    ops = _ops(tmp_path, raw, session_id=session_id)
    if protocol_version == "2.0.0":
        ops.create_session(protocol_version="2.0.0")
    else:
        ops.create_session()
    _append(ops, EventType.ASSUMPTION_CREATED, _assumption_payload(), 1)
    for index, work_item in enumerate(work_items, start=2):
        _append(ops, EventType.WORK_ITEM_CREATED, work_item, index)
    ops.rebuild_ledger()
    return ops


def _assumption(handle: str, label: str, *, evidence_status: str) -> dict:
    return {
        "tmp_handle": handle,
        "intake_label": label,
        "statement": f"External fact {label}",
        "status": "candidate",
        "source_type": "external_required",
        "source_excerpt": None,
        "blast_radius": "high",
        "downstream_impact": "Implementation correctness",
        "risk_if_wrong": "The system may rely on an unvalidated external fact",
        "evidence_status": evidence_status,
        "external_fact": f"External validation target {label}",
    }


def _intake(assumption: dict) -> dict:
    return {
        "session_frame": {
            "topic": "payment retries",
            "downstream_use": "implementation",
            "closure_standard": "blockers resolved or carried",
            "input_mode": "unstructured",
        },
        "assumptions": [assumption],
        "work_items": [],
        "risks": [],
        "terms": [],
        "decisions": [],
        "contradictions": [],
    }


def _run_external_required_intake(tmp_path, proposed_status: str, *, session_id: str):
    ops = _ops(
        tmp_path,
        canonical.dumps_event_line(
            _intake(_assumption("tmp_assumption_1", "CA-01", evidence_status=proposed_status))
        ),
        session_id=session_id,
    )
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE)
    result = ops.run_intake()
    assert result.accepted
    return ops.ledger()["assumptions"][0]


def test_external_required_intake_finalizes_to_external_validation_required(tmp_path):
    assumption = _run_external_required_intake(
        tmp_path, "undecidable", session_id="external_required"
    )

    assert assumption["source_type"] == "external_required"
    assert assumption["evidence_status"] == "external_validation_required"


def test_external_required_cannot_project_as_verified_user_stated(tmp_path):
    assumption = _run_external_required_intake(
        tmp_path, "verified_user_stated", session_id="external_verified"
    )

    assert assumption["source_type"] == "external_required"
    assert assumption["evidence_status"] == "external_validation_required"


def test_external_required_cannot_project_as_ordinary_model_inferred(tmp_path):
    assumption = _run_external_required_intake(
        tmp_path, "model_inferred", session_id="external_model_inferred"
    )

    assert assumption["source_type"] == "external_required"
    assert assumption["evidence_status"] == "external_validation_required"


def test_v2_rank_selects_unresolved_blocking_work_before_non_blocking_work(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0002"),
        _work_payload("W-0001", blast_radius="medium", blocks_closure=False),
        _work_payload("W-0002", blast_radius="high", blocks_closure=True),
    )

    active = ops.ask_next()

    assert active["id"] == "W-0002"
    assert active["status"] == "active"


def test_v2_rank_rejects_non_blocking_selection_while_blockers_exist(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", blast_radius="medium", blocks_closure=False),
        _work_payload("W-0002", blast_radius="high", blocks_closure=True),
    )

    with pytest.raises(OperationError, match="unresolved premise blockers"):
        ops.ask_next()

    assert not [item for item in ops.ledger()["work_items"] if item["status"] == "active"]
    assert ops.event_log.read_events()[-1]["event_type"] == "PROPOSAL_REJECTED"


def test_v2_rank_does_not_deadlock_when_blockers_exist(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", blast_radius="high", blocks_closure=True),
        _work_payload("W-0002", blast_radius="medium", blocks_closure=False),
    )

    active = ops.ask_next()

    assert active["id"] == "W-0001"
    assert active["status"] == "active"


def test_v2_active_work_item_rule_is_enforced_by_rank_validation(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0002"),
        _work_payload("W-0001", status="active", blast_radius="medium", blocks_closure=False),
        _work_payload("W-0002", blast_radius="high", blocks_closure=True),
    )

    with pytest.raises(OperationError, match="already active"):
        ops.ask_next()

    model_events = [
        event for event in ops.event_log.read_events() if event["event_type"] == "MODEL_RESPONSE_RECORDED"
    ]
    assert model_events[-1]["payload"]["accepted"] is False
    assert ops.event_log.read_events()[-1]["event_type"] == "PROPOSAL_REJECTED"


def test_v2_active_non_blocking_selection_is_allowed_even_when_blockers_exist(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", status="active", blast_radius="medium", blocks_closure=False),
        _work_payload("W-0002", blast_radius="high", blocks_closure=True),
    )

    active = ops.ask_next()

    assert active["id"] == "W-0001"
    assert active["status"] == "active"


def test_v2_rank_rejects_resolved_work(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", status="resolved", blast_radius="high", blocks_closure=True),
    )

    with pytest.raises(OperationError, match="resolved"):
        ops.ask_next()


def test_v2_rank_rejects_nonexistent_work(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-9999"),
        _work_payload("W-0001", blast_radius="high", blocks_closure=True),
    )

    with pytest.raises(OperationError, match="does not exist"):
        ops.ask_next()


@pytest.mark.parametrize(
    ("recommended_default", "recommended_default_basis"),
    [
        ("Confirm by default", None),
        (None, "A-9999"),
    ],
)
def test_rank_rejects_missing_or_invalid_recommended_default_basis(
    tmp_path, recommended_default, recommended_default_basis
):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output(
            "W-0001",
            recommended_default=recommended_default,
            recommended_default_basis=recommended_default_basis,
        ),
        _work_payload("W-0001", blast_radius="high", blocks_closure=True),
    )

    with pytest.raises(OperationError, match="recommended default basis"):
        ops.ask_next()


def test_v2_rank_allows_high_blocker_without_blocking_reason(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", blast_radius="high", blocks_closure=True),
    )

    active = ops.ask_next()

    assert active["id"] == "W-0001"


def test_v2_rank_rejects_medium_blocker_without_blocking_reason(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", blast_radius="medium", blocks_closure=True),
    )

    with pytest.raises(OperationError, match="blocking_reason"):
        ops.ask_next()


def test_v1_rank_and_ask_next_do_not_gain_v2_blocker_priority(tmp_path):
    ops = _seed_rank_session(
        tmp_path,
        _rank_output("W-0001"),
        _work_payload("W-0001", blast_radius="medium", blocks_closure=False),
        _work_payload("W-0002", blast_radius="high", blocks_closure=True),
        protocol_version="1.0.0",
        session_id="v1_rank",
    )

    active = ops.ask_next()

    assert "protocol_version" not in ops.ledger()
    assert active["id"] == "W-0001"
