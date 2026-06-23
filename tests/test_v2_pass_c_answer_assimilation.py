"""V2 Pass C: answer assimilation for premise-control work."""

from __future__ import annotations

import pytest

from interrogation_harness import canonical
from interrogation_harness.events import Actor, EventType
from interrogation_harness.interrogation import OperationError
from interrogation_harness.model.adapter import ModelJob
from interrogation_harness.operations import HarnessOperations
from interrogation_harness.projection import ProjectionError

TS = "2026-01-01T00:00:00Z"
ANSWER = "The adapter retries payments exactly once and requires idempotency keys."


class _JobModel:
    """Return canned output by model job."""

    def __init__(self, *, answer_raw: str, rank_raw: str | None = None) -> None:
        self.answer_raw = answer_raw
        self.rank_raw = rank_raw or _rank_output("W-0001")

    def complete(self, request, *, scenario=None):
        if request.job == ModelJob.INTERPRET_USER_ANSWER:
            return self.answer_raw
        if request.job == ModelJob.RANK_NEXT_WORK_ITEM:
            return self.rank_raw
        raise AssertionError(f"unexpected job: {request.job}")


def _raw(obj: dict) -> str:
    return canonical.dumps_event_line(obj)


def _interpret(
    proposed_events: list[dict],
    *,
    followup_required: bool = False,
    revision_required: bool = False,
    warnings: list[str] | None = None,
) -> str:
    return _raw(
        {
            "proposed_events": proposed_events,
            "followup_required": followup_required,
            "revision_required": revision_required,
            "warnings": warnings or [],
        }
    )


def _transition(event_type: str, target: str, frm: str, to: str, **extra) -> dict:
    payload = {"from": frm, "to": to, "reason": extra.pop("reason", "answer assimilation")}
    payload.update(extra)
    return {"event_type": event_type, "target_ref": target, "payload": payload}


def _create_assumption(handle: str = "tmp_assumption_1", **overrides) -> dict:
    payload = {
        "tmp_handle": handle,
        "statement": "The adapter retries payments exactly once.",
        "status": "candidate",
        "source_type": "user_stated",
        "source_excerpt": "adapter retries payments exactly once",
        "blast_radius": "high",
        "downstream_impact": "Retry implementation",
        "risk_if_wrong": "Duplicate or missing payments",
        "evidence_status": "model_inferred",
    }
    payload.update(overrides)
    return {"event_type": "ASSUMPTION_CREATED", "target_ref": handle, "payload": payload}


def _create_work(handle: str = "tmp_work_1", **overrides) -> dict:
    payload = {
        "tmp_handle": handle,
        "kind": "resolve_assumption",
        "question": "What follow-up premise must be resolved?",
        "why_it_matters": "It controls implementation correctness.",
        "what_breaks_if_wrong": "The downstream build may rely on a false premise.",
        "blast_radius": "high",
        "blocks_closure": True,
        "related_temp_refs": ["A-0001"],
        "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
    }
    payload.update(overrides)
    return {"event_type": "WORK_ITEM_CREATED", "target_ref": handle, "payload": payload}


def _rank_output(selected: str, *, tested: str | None = "A-0001") -> str:
    return _raw(
        {
            "selected_work_item_id": selected,
            "question": "Confirm the next premise?",
            "why_it_matters": "It controls implementation correctness.",
            "what_breaks_if_wrong": "The downstream build may rely on a false premise.",
            "tested_entity_id": tested,
            "recommended_default": None,
            "recommended_default_basis": None,
            "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
        }
    )


def _append(ops: HarnessOperations, event_type: EventType, payload: dict, n: int) -> None:
    ops.event_log.append(
        event_type=event_type,
        actor=Actor.HARNESS,
        session_id=ops.session_id,
        correlation_id=f"seed-{n}",
        idempotency_key=f"seed-{ops.session_id}-{n}",
        timestamp=TS,
        payload=payload,
    )


def _assumption_payload(*, status: str = "candidate") -> dict:
    return {
        "id": "A-0001",
        "statement": "Payments require idempotency keys.",
        "status": status,
        "source_type": "user_stated",
        "source_excerpt": "Payments require idempotency keys.",
        "source_excerpt_verified": True,
        "blast_radius": "high",
        "downstream_impact": "Payment retries",
        "risk_if_wrong": "Duplicate charges",
        "evidence_status": "verified_user_stated",
        "premise_origin": "intake",
    }


def _work_payload(
    ident: str,
    *,
    status: str = "active",
    blast_radius: str = "high",
    blocks_closure: bool = True,
    target_entity: str | None = "A-0001",
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
        "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
    }
    if target_entity is not None:
        payload["target_entity"] = target_entity
    return payload


def _seed_v2_session(
    tmp_path,
    answer_raw: str,
    *,
    rank_raw: str | None = None,
    assumption_status: str = "candidate",
    work_status: str = "active",
    extra_work: list[dict] | None = None,
    session_id: str = "v2_answer",
) -> HarnessOperations:
    ops = HarnessOperations(
        tmp_path / "sessions",
        session_id,
        model=_JobModel(answer_raw=answer_raw, rank_raw=rank_raw),
        now=lambda: TS,
    )
    ops.create_session(protocol_version="2.0.0")
    _append(ops, EventType.ASSUMPTION_CREATED, _assumption_payload(status=assumption_status), 1)
    _append(ops, EventType.WORK_ITEM_CREATED, _work_payload("W-0001", status=work_status), 2)
    for index, work_item in enumerate(extra_work or [], start=3):
        _append(ops, EventType.WORK_ITEM_CREATED, work_item, index)
    ops.rebuild_ledger()
    return ops


def test_v2_interpret_resolves_active_work_through_legal_transition(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered")]),
    )

    result = ops.answer(ANSWER)

    assert result.accepted
    assert ops.ledger()["work_items"][0]["status"] == "resolved"


def test_v2_interpret_rejects_non_active_work_transition(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_transition("WORK_ITEM_STATUS_CHANGED", "W-0002", "open", "deferred")]),
        extra_work=[_work_payload("W-0002", status="open", blocks_closure=False, blast_radius="medium")],
    )

    result = ops.answer(ANSWER)

    assert not result.accepted
    assert "active work item" in result.errors[0]


def test_v2_interpret_rejects_no_active_work(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([]),
        work_status="open",
    )

    with pytest.raises(OperationError, match="exactly one active"):
        ops.answer(ANSWER)


def test_v2_interpret_rejects_multiple_active_work_items(tmp_path):
    ops = HarnessOperations(
        tmp_path / "sessions",
        "multi_active",
        model=_JobModel(answer_raw=_interpret([])),
        now=lambda: TS,
    )
    ops.create_session(protocol_version="2.0.0")
    _append(ops, EventType.ASSUMPTION_CREATED, _assumption_payload(), 1)
    _append(ops, EventType.WORK_ITEM_CREATED, _work_payload("W-0001", status="active"), 2)
    _append(ops, EventType.WORK_ITEM_CREATED, _work_payload("W-0002", status="active"), 3)

    with pytest.raises(ProjectionError, match="more than one active"):
        ops.answer(ANSWER)


def test_v2_interpret_rejects_nonexistent_target_ref(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_transition("ASSUMPTION_TRANSITIONED", "A-9999", "candidate", "locked")]),
    )

    result = ops.answer(ANSWER)

    assert not result.accepted
    assert "target reference does not exist" in result.errors[0]


def test_v2_interpret_rejects_wrong_entity_type_transition(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_transition("ASSUMPTION_TRANSITIONED", "W-0001", "candidate", "locked")]),
    )

    result = ops.answer(ANSWER)

    assert not result.accepted
    assert "wrong entity type" in result.errors[0]


def test_v2_interpret_rejects_from_status_mismatch(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "open", "answered")]),
    )

    result = ops.answer(ANSWER)

    assert not result.accepted
    assert "from mismatch" in result.errors[0]


def test_answer_origin_user_stated_assumption_is_stamped_and_verified(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_assumption(evidence_status="undecidable"),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ]
        ),
    )

    result = ops.answer(ANSWER)
    created = ops.ledger()["assumptions"][1]

    assert result.accepted
    assert created["premise_origin"] == "answer"
    assert created["source_type"] == "user_stated"
    assert created["source_excerpt_verified"] is True
    assert created["evidence_status"] == "verified_user_stated"


def test_answer_origin_unverifiable_user_stated_is_downgraded(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_assumption(source_excerpt="not present in the answer"),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ]
        ),
    )

    result = ops.answer(ANSWER)
    created = ops.ledger()["assumptions"][1]

    assert result.accepted
    assert created["source_type"] == "model_inferred"
    assert created["source_excerpt_verified"] is False
    assert created["evidence_status"] == "model_inferred"


def test_answer_origin_external_required_finalizes_to_external_validation_required(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_assumption(
                    source_type="external_required",
                    source_excerpt=None,
                    evidence_status="verified_user_stated",
                    external_fact="Processor retry guarantee",
                ),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ]
        ),
    )

    result = ops.answer(ANSWER)
    created = ops.ledger()["assumptions"][1]

    assert result.accepted
    assert created["source_type"] == "external_required"
    assert created["evidence_status"] == "external_validation_required"


def test_answer_origin_model_inferred_verified_claim_is_forced_down(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_assumption(
                    source_type="model_inferred",
                    source_excerpt=None,
                    evidence_status="verified_user_stated",
                ),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ]
        ),
    )

    result = ops.answer(ANSWER)
    created = ops.ledger()["assumptions"][1]

    assert result.accepted
    assert created["source_type"] == "model_inferred"
    assert created["evidence_status"] == "model_inferred"


def test_answer_created_blocker_obeys_d5_and_is_ranked_next(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_work(),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ]
        ),
        rank_raw=_rank_output("W-0002"),
    )

    result = ops.answer(ANSWER)
    active = ops.ask_next()

    assert result.accepted
    assert active["id"] == "W-0002"
    assert active["blocks_closure"] is True


@pytest.mark.parametrize(
    "work_overrides",
    [
        {"blast_radius": "high", "blocks_closure": False},
        {"blast_radius": "medium", "blocks_closure": True},
        {"blast_radius": "low", "blocks_closure": True},
    ],
)
def test_answer_created_work_rejects_d5_violations(tmp_path, work_overrides):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_create_work(**work_overrides)]),
    )

    result = ops.answer(ANSWER)

    assert not result.accepted


def test_answer_created_work_validates_recommended_default_basis(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_work(
                    recommended_default="Assume retry",
                    recommended_default_basis="A-9999",
                )
            ]
        ),
    )

    result = ops.answer(ANSWER)

    assert not result.accepted
    assert "recommended default basis" in result.errors[0]


def test_v2_revision_is_represented_through_legal_transition(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _transition(
                    "ASSUMPTION_TRANSITIONED",
                    "A-0001",
                    "locked",
                    "revised",
                    prior_statement="Payments require idempotency keys.",
                    new_statement="Payment writes require idempotency keys.",
                ),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ],
            revision_required=True,
        ),
        assumption_status="locked",
    )

    result = ops.answer(ANSWER)
    assumption = ops.ledger()["assumptions"][0]

    assert result.accepted
    assert assumption["status"] == "revised"
    assert assumption["revision_history"][0]["prior_statement"] == "Payments require idempotency keys."


def test_v2_revision_required_rejects_silent_resolution(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [_transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered")],
            revision_required=True,
        ),
    )

    result = ops.answer(ANSWER)

    assert not result.accepted
    assert "revision_required" in result.errors[0]


def test_unresolved_active_blocker_remains_selectable_after_answer(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([], followup_required=True),
        rank_raw=_rank_output("W-0001"),
    )

    result = ops.answer(ANSWER)
    active = ops.ask_next()

    assert result.accepted
    assert active["id"] == "W-0001"
    assert active["status"] == "active"


def test_new_blocker_is_selected_before_non_blocking_work_after_answer(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret(
            [
                _create_work("tmp_work_1"),
                _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered"),
            ]
        ),
        rank_raw=_rank_output("W-0003"),
        extra_work=[_work_payload("W-0002", status="open", blast_radius="medium", blocks_closure=False)],
    )

    result = ops.answer(ANSWER)
    active = ops.ask_next()

    assert result.accepted
    assert active["id"] == "W-0003"
    assert active["blocks_closure"] is True


def test_ask_next_does_not_deadlock_after_active_work_resolves(tmp_path):
    ops = _seed_v2_session(
        tmp_path,
        _interpret([_transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered")]),
        rank_raw=_rank_output("W-0002"),
        extra_work=[_work_payload("W-0002", status="open", blast_radius="medium", blocks_closure=False)],
    )

    result = ops.answer(ANSWER)
    active = ops.ask_next()

    assert result.accepted
    assert active["id"] == "W-0002"


def test_v1_interpret_user_answer_remains_compatible_without_v2_fields(tmp_path):
    ops = HarnessOperations(
        tmp_path / "sessions",
        "v1_answer",
        model=_JobModel(
            answer_raw=_raw(
                {
                    "proposed_events": [
                        _transition("WORK_ITEM_STATUS_CHANGED", "W-0001", "active", "answered")
                    ],
                    "followup_required": False,
                    "warnings": [],
                }
            )
        ),
        now=lambda: TS,
    )
    ops.create_session()
    _append(ops, EventType.ASSUMPTION_CREATED, _assumption_payload(status="candidate"), 1)
    _append(ops, EventType.WORK_ITEM_CREATED, _work_payload("W-0001", status="active"), 2)
    ops.rebuild_ledger()

    result = ops.answer(ANSWER)

    assert result.accepted
    assert "protocol_version" not in ops.ledger()
    assert ops.ledger()["work_items"][0]["status"] == "resolved"
