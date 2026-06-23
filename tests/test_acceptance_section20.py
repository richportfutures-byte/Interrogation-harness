"""Complete Section 20 acceptance suite against the deterministic mock model."""

from __future__ import annotations

from pathlib import Path

import pytest

from interrogation_harness import canonical
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.model import DeterministicMockModel, MockScenario, ModelJob
from interrogation_harness.operations import HarnessOperations, content_hash
from interrogation_harness.projection import LedgerProjector
from interrogation_harness.session_store import SessionStore
from interrogation_harness.validation import ModelContractValidator

TS = "2026-01-01T00:00:00Z"
SID = "acceptance"


class ScriptedAdapter:
    """Offline test adapter that returns raw canned outputs."""

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, request, *, scenario=None):
        self.calls += 1
        return self.outputs[min(self.calls - 1, len(self.outputs) - 1)]


def _raw(obj) -> str:
    return canonical.dumps_event_line(obj)


def _ops(tmp_path, session_id: str = SID, model=None) -> HarnessOperations:
    return HarnessOperations(
        tmp_path / "sessions",
        session_id,
        model=model or DeterministicMockModel(),
        now=lambda: TS,
    )


def _events(ops: HarnessOperations) -> list[dict]:
    return ops.event_log.read_events()


def _types(ops: HarnessOperations) -> list[str]:
    return [event["event_type"] for event in _events(ops)]


def _model_events(ops: HarnessOperations) -> list[dict]:
    return [event for event in _events(ops) if event["event_type"] == "MODEL_RESPONSE_RECORDED"]


def _extracted_ops(tmp_path, *, source: str | None = None) -> HarnessOperations:
    source_text = source or "Messy notes:\n\nPayments require   idempotency keys.\n"
    ops = _ops(tmp_path)
    ops.create_session()
    ops.add_source(source_text)
    result = ops.run_initial_extraction()
    assert result.accepted
    return ops


def _active_ops(tmp_path) -> HarnessOperations:
    ops = _extracted_ops(tmp_path)
    ops.ask_next()
    return ops


def _seed_provisional_active(tmp_path) -> HarnessOperations:
    ops = _ops(tmp_path)
    ops.store.create()
    log = ops.event_log
    _append(
        log,
        EventType.SESSION_CREATED,
        {"session_id": SID},
        0,
    )
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0001",
            "statement": "Payments require idempotency keys.",
            "status": "provisional",
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
            "status": "active",
            "question": "Should payment retries be idempotent?",
            "why_it_matters": "payments",
            "what_breaks_if_wrong": "duplicate charges",
            "blast_radius": "high",
            "blocks_closure": True,
            "target_entity": "A-0001",
            "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
        },
        2,
    )
    ops.rebuild_ledger()
    return ops


def _append(log: EventLog, event_type: EventType, payload: dict, n: int, *, actor=Actor.HARNESS):
    return log.append(
        event_type=event_type,
        actor=actor,
        session_id=SID,
        correlation_id=f"seed-{n}",
        idempotency_key=f"seed-key-{n}",
        timestamp=TS,
        payload=payload,
    )


def _initial_output(source_excerpt: str) -> dict:
    return {
        "assumptions": [
            {
                "tmp_handle": "tmp_assumption_1",
                "statement": "The billing worker owns payment writes.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": source_excerpt,
                "blast_radius": "high",
                "downstream_impact": "Payment architecture",
                "risk_if_wrong": "Duplicate or missing payments",
            }
        ],
        "work_items": [],
        "risks": [],
        "terms": [],
        "decisions": [],
        "contradictions": [],
    }


# Group 1: Section 20 tests 1 through 9.


def test_01_create_session_records_session_created(tmp_path):
    ops = _ops(tmp_path)
    ledger = ops.create_session()

    assert ops.store.events_path.exists()
    assert _types(ops) == ["SESSION_CREATED"]
    assert _events(ops)[0]["payload"] == {"session_id": SID}
    assert ledger["session_id"] == SID


def test_02_add_source_writes_full_file_and_hash(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    messy = "Messy source\n\nPayments require   idempotency keys.\n"
    ledger = ops.add_source(messy)

    assert ops.store.read_source() == messy
    source_event = _events(ops)[-1]
    assert source_event["event_type"] == "SOURCE_ADDED"
    assert source_event["payload"]["content_hash"] == content_hash(messy)
    assert ledger["source_hash"] == content_hash(messy)


def test_03_initial_extraction_appends_creation_events_and_rebuilds_ledger(tmp_path):
    ops = _extracted_ops(tmp_path)
    types = _types(ops)
    ledger = ops.store.read_ledger()

    assert types.count("MODEL_RESPONSE_RECORDED") == 1
    assert types.count("ASSUMPTION_CREATED") == 2
    assert types.count("WORK_ITEM_CREATED") == 1
    assert len(ledger["assumptions"]) == 2
    assert len(ledger["work_items"]) == 1
    assert ledger == ops.ledger()


def test_04_event_log_exists_append_only_and_contains_expected_accepted_events(tmp_path):
    ops = _extracted_ops(tmp_path)
    before = ops.store.read_event_lines()
    ops.show_ledger()
    after_read_only = ops.store.read_event_lines()

    assert ops.store.events_path.exists()
    assert before == after_read_only
    assert "SESSION_CREATED" in _types(ops)
    assert "SOURCE_ADDED" in _types(ops)
    assert any(
        event["event_type"] == "MODEL_RESPONSE_RECORDED"
        and event["payload"]["accepted"] is True
        for event in _events(ops)
    )
    assert "ASSUMPTION_CREATED" in _types(ops)
    assert "WORK_ITEM_CREATED" in _types(ops)


def test_05_ledger_reconstructed_solely_from_events(tmp_path):
    ops = _extracted_ops(tmp_path)
    original = ops.store.ledger_path.read_text(encoding="utf-8")
    ops.store.ledger_path.write_text('{"not":"authoritative"}\n', encoding="utf-8")

    rebuilt = ops.rebuild_ledger()

    assert canonical.dumps_ledger(rebuilt) == original
    assert ops.store.ledger_path.read_text(encoding="utf-8") == original


def test_06_temp_handles_map_to_harness_minted_ids_via_ref_map(tmp_path):
    ops = _extracted_ops(tmp_path)
    creation_events = [
        event for event in _events(ops) if "ref_map" in event
    ]

    ref_maps = [event["ref_map"] for event in creation_events]
    assert {"tmp_assumption_1": "A-0001"} in ref_maps
    assert {"tmp_assumption_2": "A-0002"} in ref_maps
    assert {"tmp_work_1": "W-0001"} in ref_maps
    assert [event["payload"]["id"] for event in creation_events] == [
        "A-0001",
        "A-0002",
        "W-0001",
    ]


def test_07_model_creation_output_with_durable_id_is_rejected(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()

    result = ModelContractValidator(ops.event_log, DeterministicMockModel()).run(
        ModelJob.INITIAL_EXTRACTION,
        session_id=SID,
        correlation_id="bad-durable",
        idempotency_key="bad-durable-key",
        timestamp=TS,
        request_payload={},
        source_markdown="source",
        scenario=MockScenario.CREATION_WITH_DURABLE_ID.value,
    )

    assert result.accepted is False
    assert "ASSUMPTION_CREATED" not in _types(ops)
    assert all(event["payload"]["accepted"] is False for event in _model_events(ops))
    assert ops.event_log.accepted_correlation("bad-durable-key") is None


def test_08_user_stated_excerpt_is_verified_against_source(tmp_path):
    source = "The billing worker owns payment writes."
    ops = _ops(tmp_path, model=ScriptedAdapter(_raw(_initial_output(source))))
    ops.create_session()
    ops.add_source(source)
    result = ops.run_initial_extraction()

    assert result.accepted
    assumption = ops.store.read_ledger()["assumptions"][0]
    assert assumption["source_type"] == "user_stated"
    assert assumption["source_excerpt_verified"] is True


def test_09_absent_user_stated_excerpt_is_downgraded_not_dropped(tmp_path):
    ops = _ops(tmp_path, model=ScriptedAdapter(_raw(_initial_output("not in source"))))
    ops.create_session()
    ops.add_source("The source says something else.")
    result = ops.run_initial_extraction()

    assert result.accepted
    assumptions = ops.store.read_ledger()["assumptions"]
    assert len(assumptions) == 1
    assert assumptions[0]["statement"] == "The billing worker owns payment writes."
    assert assumptions[0]["source_type"] == "model_inferred"
    assert assumptions[0]["source_excerpt_verified"] is False


# Group 2: Section 20 tests 10 through 19.


def test_10_exactly_one_work_item_is_active_after_ask_next(tmp_path):
    ops = _extracted_ops(tmp_path)
    active = ops.ask_next()
    ledger = ops.store.read_ledger()

    assert active["id"] == "W-0001"
    assert [item["id"] for item in ledger["work_items"] if item["status"] == "active"] == [
        "W-0001"
    ]
    assert _types(ops)[-1] == "QUESTION_ASKED"


def test_11_confirm_legally_locks_provisional_assumption(tmp_path):
    ops = _seed_provisional_active(tmp_path)
    result = ops.answer("confirm")
    ledger = ops.store.read_ledger()

    assert result.accepted
    assert ledger["assumptions"][0]["status"] == "locked"
    assert ledger["work_items"][0]["status"] == "resolved"
    assert "ASSUMPTION_TRANSITIONED" in _types(ops)


def test_12_rejected_to_locked_proposal_is_refused_without_mutation(tmp_path):
    ops = _ops(tmp_path)
    ops.store.create()
    _append(ops.event_log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
    _append(
        ops.event_log,
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
        ops.event_log,
        EventType.ASSUMPTION_TRANSITIONED,
        {"id": "A-0001", "from": "candidate", "to": "rejected", "reason": "no"},
        2,
    )
    before = ops.rebuild_ledger()

    result = ModelContractValidator(ops.event_log, DeterministicMockModel()).run(
        ModelJob.INTERPRET_USER_ANSWER,
        session_id=SID,
        correlation_id="illegal-rejected-lock",
        idempotency_key="illegal-rejected-lock-key",
        timestamp=TS,
        request_payload={},
        scenario=MockScenario.ILLEGAL_TRANSITION.value,
    )
    after = ops.ledger()

    assert result.accepted is False
    assert after == before
    assert "PROPOSAL_REJECTED" in _types(ops)
    assert ops.event_log.accepted_correlation("illegal-rejected-lock-key") is None


def test_13_locked_assumption_changes_only_through_revised(tmp_path):
    ops = _seed_provisional_active(tmp_path)
    assert ops.answer("confirm").accepted
    locked = ops.store.read_ledger()["assumptions"][0]
    assert locked["status"] == "locked"
    before = ops.ledger()
    illegal_locked_reject = _raw(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": "A-0001",
                    "payload": {
                        "from": "locked",
                        "to": "rejected",
                        "reason": "try to overwrite locked",
                    },
                }
            ],
            "followup_required": False,
            "warnings": [],
        }
    )

    result = ModelContractValidator(
        ops.event_log, ScriptedAdapter(illegal_locked_reject)
    ).run(
        ModelJob.INTERPRET_USER_ANSWER,
        session_id=SID,
        correlation_id="locked-reject",
        idempotency_key="locked-reject-key",
        timestamp=TS,
        request_payload={},
    )

    assert result.accepted is False
    assert ops.ledger() == before
    revised = ops.revise("A-0001", "Payment writes require idempotency keys.")
    assert revised["status"] == "revised"
    assert revised["statement"] == "Payment writes require idempotency keys."


def test_14_revision_preserves_prior_statement_in_history(tmp_path):
    ops = _seed_provisional_active(tmp_path)
    assert ops.answer("confirm").accepted
    revised = ops.revise("A-0001", "Payment writes require idempotency keys.")

    assert revised["revision_history"]
    entry = revised["revision_history"][0]
    assert entry["prior_statement"] == "Payments require idempotency keys."
    assert entry["new_statement"] == "Payment writes require idempotency keys."
    assert entry["event_id"].startswith("E-")


def test_15_unknown_routes_to_open_risk_or_deferred_work_and_does_not_stall(tmp_path):
    ops = _active_ops(tmp_path)
    result = ops.answer("unknown")
    ledger = ops.store.read_ledger()

    assert result.accepted
    assert any(item["status"] == "open" for item in ledger["risks"]) or any(
        item["status"] == "deferred" for item in ledger["work_items"]
    ) or any(
        item["kind"] == "validate_external" and item["status"] != "resolved"
        for item in ledger["work_items"]
    )
    active = ops.ask_next()
    assert active["status"] == "active"


def test_16_defer_does_not_stall_the_loop(tmp_path):
    ops = _active_ops(tmp_path)
    deferred = ops.defer(reason="answer later")

    assert deferred["status"] == "deferred"
    active = ops.ask_next()
    assert active["id"] == deferred["id"]
    assert active["status"] == "active"


def test_17_malformed_json_does_not_mutate_ledger_and_is_recorded(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    before = ops.ledger()

    result = ModelContractValidator(ops.event_log, DeterministicMockModel()).run(
        ModelJob.INTERPRET_USER_ANSWER,
        session_id=SID,
        correlation_id="malformed",
        idempotency_key="malformed-key",
        timestamp=TS,
        request_payload={},
        scenario=MockScenario.MALFORMED_JSON.value,
    )

    assert result.accepted is False
    assert ops.ledger() == before
    recorded = _model_events(ops)
    assert len(recorded) == 2
    assert all(event["payload"]["accepted"] is False for event in recorded)


def test_18_illegal_transition_records_rejection_and_does_not_mutate(tmp_path):
    ops = _ops(tmp_path)
    ops.store.create()
    _append(ops.event_log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
    _append(
        ops.event_log,
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
        ops.event_log,
        EventType.ASSUMPTION_TRANSITIONED,
        {"id": "A-0001", "from": "candidate", "to": "rejected", "reason": "no"},
        2,
    )
    before = ops.rebuild_ledger()

    result = ModelContractValidator(ops.event_log, DeterministicMockModel()).run(
        ModelJob.INTERPRET_USER_ANSWER,
        session_id=SID,
        correlation_id="proposal-rejected",
        idempotency_key="proposal-rejected-key",
        timestamp=TS,
        request_payload={},
        scenario=MockScenario.ILLEGAL_TRANSITION.value,
    )

    assert result.accepted is False
    assert ops.ledger() == before
    rejection = [event for event in _events(ops) if event["event_type"] == "PROPOSAL_REJECTED"][0]
    assert "rejected -> locked" in rejection["payload"]["reason"]


def test_19_rerun_same_accepted_idempotency_key_adds_no_duplicates(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    ops.add_source("Payments require idempotency keys.")
    first = ops.run_initial_extraction()
    before_events = ops.store.read_event_lines()
    before_ledger = ops.store.ledger_path.read_text(encoding="utf-8")

    second = ops.run_initial_extraction()

    assert first.accepted
    assert second.accepted
    assert ops.store.read_event_lines() == before_events
    assert ops.store.ledger_path.read_text(encoding="utf-8") == before_ledger
    assert len(ops.store.read_ledger()["assumptions"]) == 2


# Group 3: Section 20 tests 20 through 25.


def test_20_ledger_delete_and_rebuild_is_byte_identical_twice(tmp_path):
    ops = _extracted_ops(tmp_path)
    first_bytes = ops.store.ledger_path.read_bytes()

    ops.store.delete_ledger()
    rebuilt_once = ops.rebuild_ledger()
    second_bytes = ops.store.ledger_path.read_bytes()
    rebuilt_twice = ops.rebuild_ledger()
    third_bytes = ops.store.ledger_path.read_bytes()

    assert canonical.dumps_ledger(rebuilt_once).encode("utf-8") == first_bytes
    assert canonical.dumps_ledger(rebuilt_twice).encode("utf-8") == first_bytes
    assert first_bytes == second_bytes == third_bytes


def test_21_audit_records_audit_run_and_converts_findings_deterministically(tmp_path):
    ops = _extracted_ops(tmp_path)
    first = ops.run_audit()
    first_ledger = ops.store.read_ledger()
    second = ops.run_audit()
    second_ledger = ops.store.read_ledger()

    assert first["accepted"] is True
    assert second["accepted"] is True
    assert _types(ops).count("AUDIT_RUN") >= 1
    assert len(first_ledger["contradictions"]) == 1
    assert len(second_ledger["contradictions"]) == 1
    assert first_ledger["contradictions"][0]["refs"] == ["A-0001", "A-0002"]
    assert second_ledger["contradictions"][0] == first_ledger["contradictions"][0]
    assert len(
        [item for item in second_ledger["work_items"] if item["kind"] == "resolve_contradiction"]
    ) == 1


def test_22_force_close_preserves_high_work_in_open_risk_register(tmp_path):
    ops = _extracted_ops(tmp_path)
    ledger = ops.force_close()
    high_work = [
        item for item in ledger["work_items"] if item["blast_radius"] == "high"
    ]

    assert high_work
    assert all(item["status"] != "resolved" for item in high_work)
    ops.generate_artifact()
    text = ops.store.artifact_path.read_text(encoding="utf-8")
    assert "## Open Risk Register" in text
    assert "W-0001 (high work item)" in text


def test_23_final_artifact_includes_locked_assumptions_risks_provenance_and_instructions(tmp_path):
    ops = _seed_provisional_active(tmp_path)
    assert ops.answer("confirm").accepted
    _append(
        ops.event_log,
        EventType.RISK_CREATED,
        {
            "id": "R-0001",
            "statement": "A payment processor outage can delay writes.",
            "severity": "high",
            "status": "open",
            "source_refs": ["A-0001"],
        },
        50,
    )
    ops.rebuild_ledger()
    ops.generate_artifact()
    text = ops.store.artifact_path.read_text(encoding="utf-8")

    assert "## Locked Assumptions" in text
    assert "Payments require idempotency keys." in text
    assert "## Open Risk Register" in text
    assert "A payment processor outage can delay writes." in text
    assert "## Provenance Index" in text
    assert "A-0001: user_stated, verified=True" in text
    assert "## Downstream Builder Instructions" in text


def test_24_final_artifact_invents_no_locked_assumption_absent_from_projection(tmp_path):
    ops = _seed_provisional_active(tmp_path)
    assert ops.answer("confirm").accepted
    ops.generate_artifact()
    ledger = ops.store.read_ledger()
    text = ops.store.artifact_path.read_text(encoding="utf-8")
    locked_statements = {
        item["statement"] for item in ledger["assumptions"] if item["status"] == "locked"
    }

    for bullet in _section_bullets(text, "Locked Assumptions"):
        assert bullet in locked_statements


def test_25_resume_session_verifies_byte_identical_rebuild(tmp_path):
    ops = _extracted_ops(tmp_path)
    ops.run_audit()
    original = ops.store.ledger_path.read_text(encoding="utf-8")

    assert ops.resume_session() is True
    assert ops.store.ledger_path.read_text(encoding="utf-8") == original


def _section_bullets(markdown: str, title: str) -> list[str]:
    bullets: list[str] = []
    in_section = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == f"## {title}"
            continue
        if in_section and stripped.startswith("- "):
            bullets.append(stripped[2:])
    return bullets
