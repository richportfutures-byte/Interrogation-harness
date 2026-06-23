"""Stage 6 proof: engines, operations, and CLI."""

from __future__ import annotations

import subprocess

from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.operations import HarnessOperations, content_hash
from interrogation_harness.session_store import SessionStore

TS = "2026-01-01T00:00:00Z"
SID = "sess_stage6"


def _ops(tmp_path, session_id: str = SID) -> HarnessOperations:
    return HarnessOperations(tmp_path / "sessions", session_id, now=lambda: TS)


def _types(ops: HarnessOperations) -> list[str]:
    return [event["event_type"] for event in ops.event_log.read_events()]


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


def _seed_confirm_session(tmp_path) -> HarnessOperations:
    ops = _ops(tmp_path)
    ops.store.create()
    log = ops.event_log
    _append(log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
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
    ops.rebuild_ledger()
    return ops


def _prepare_extracted_session(tmp_path) -> HarnessOperations:
    ops = _ops(tmp_path)
    ops.create_session()
    ops.add_source("Payments require idempotency keys.")
    result = ops.run_initial_extraction()
    assert result.accepted is True
    return ops


def test_create_session_appends_session_created(tmp_path):
    ops = _ops(tmp_path)
    ledger = ops.create_session()

    assert ops.store.events_path.exists()
    assert _types(ops) == ["SESSION_CREATED"]
    assert ledger["session_id"] == SID


def test_add_source_writes_file_and_hashes_full_file(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    source = "first line\n"
    ledger = ops.add_source(source)

    assert ops.store.read_source() == source
    event = ops.event_log.read_events()[-1]
    assert event["event_type"] == "SOURCE_ADDED"
    assert event["payload"]["content_hash"] == content_hash(source)
    assert ledger["source_hash"] == content_hash(source)


def test_run_initial_extraction_uses_mock_validates_and_rebuilds(tmp_path):
    ops = _prepare_extracted_session(tmp_path)

    assert ops.store.ledger_exists()
    ledger = ops.store.read_ledger()
    assert [item["id"] for item in ledger["assumptions"]] == ["A-0001", "A-0002"]
    assert [item["id"] for item in ledger["work_items"]] == ["W-0001"]
    assert "MODEL_RESPONSE_RECORDED" in _types(ops)
    assert "ASSUMPTION_CREATED" in _types(ops)


def test_ask_next_marks_exactly_one_active_and_records_question(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    active = ops.ask_next()
    ledger = ops.store.read_ledger()

    assert active["id"] == "W-0001"
    assert [item["id"] for item in ledger["work_items"] if item["status"] == "active"] == ["W-0001"]
    assert _types(ops)[-1] == "QUESTION_ASKED"


def test_answer_confirm_routes_through_validation_and_locks_legally(tmp_path):
    ops = _seed_confirm_session(tmp_path)
    result = ops.answer("confirm")
    ledger = ops.store.read_ledger()

    assert result.accepted is True
    assert ledger["assumptions"][0]["status"] == "locked"
    assert ledger["work_items"][0]["status"] == "resolved"
    model_events = [e for e in ops.event_log.read_events() if e["event_type"] == "MODEL_RESPONSE_RECORDED"]
    assert model_events[-1]["payload"]["job"] == "interpret_user_answer"
    assert model_events[-1]["payload"]["accepted"] is True


def test_answer_confirm_after_initial_extraction_locks_candidate(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    ops.ask_next()
    result = ops.answer("confirm")
    ledger = ops.store.read_ledger()

    assert result.accepted is True
    assert ledger["assumptions"][0]["status"] == "locked"
    assert ledger["work_items"][0]["status"] == "resolved"


def test_answer_unknown_keeps_loop_moving_with_open_risk_or_deferred_work(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    ops.ask_next()
    result = ops.answer("unknown")
    ledger = ops.store.read_ledger()

    assert result.accepted is True
    assert any(item["status"] == "open" for item in ledger["risks"])
    assert any(item["status"] == "deferred" for item in ledger["work_items"])


def test_defer_moves_work_item_and_can_be_asked_again(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    ops.ask_next()
    deferred = ops.defer(reason="later")

    assert deferred["status"] == "deferred"
    active = ops.ask_next()
    assert active["status"] == "active"
    assert active["id"] == "W-0001"


def test_run_audit_records_and_converts_findings_deterministically(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    first = ops.run_audit()
    second = ops.run_audit()
    ledger = ops.store.read_ledger()

    assert first["accepted"] is True
    assert second["accepted"] is True
    assert "AUDIT_RUN" in _types(ops)
    assert len(ledger["contradictions"]) == 1
    assert len([item for item in ledger["work_items"] if item["kind"] == "resolve_contradiction"]) == 1


def test_force_close_runs_audit_first_and_preserves_unresolved_high_work(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    ledger = ops.force_close()
    types = _types(ops)

    assert ledger["force_closed"] is True
    assert "AUDIT_RUN" in types
    assert types.index("AUDIT_RUN") < types.index("FORCE_CLOSED")
    high = [item for item in ledger["work_items"] if item["blast_radius"] == "high"]
    assert high
    assert all(item["status"] != "resolved" for item in high)


def test_generate_artifact_writes_projection_only_artifact(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    ops.force_close()
    result = ops.generate_artifact()
    text = ops.store.artifact_path.read_text(encoding="utf-8")

    assert result["accepted"] is True
    assert "## Open Risk Register" in text
    assert "W-0001" in text
    assert "Downstream Builder Instructions" in text
    assert "ARTIFACT_GENERATED" in _types(ops)


def test_resume_session_verifies_byte_identical_rebuild(tmp_path):
    ops = _prepare_extracted_session(tmp_path)
    ops.rebuild_ledger()

    assert ops.resume_session() is True


def test_cli_can_run_end_to_end_mock_loop(tmp_path):
    root = tmp_path / "cli-sessions"
    session_id = "cli_demo"

    def run(*args):
        return subprocess.run(
            ["uv", "run", "python", "-m", "interrogation_harness", "--root", str(root), *args],
            check=True,
            text=True,
            capture_output=True,
        )

    run("create-session", session_id)
    run("add-source", session_id, "Payments require idempotency keys.")
    run("run-initial-extraction", session_id)
    run("ask-next", session_id)
    run("answer", session_id, "unknown")
    run("run-audit", session_id)
    run("force-close", session_id)
    run("generate-artifact", session_id)

    store = SessionStore(root, session_id)
    assert store.artifact_path.exists()
    log = EventLog(store)
    types = [event["event_type"] for event in log.read_events()]
    assert "SESSION_CREATED" in types
    assert "SOURCE_ADDED" in types
    assert "QUESTION_ASKED" in types
    assert "AUDIT_RUN" in types
    assert "FORCE_CLOSED" in types
    assert "ARTIFACT_GENERATED" in types
