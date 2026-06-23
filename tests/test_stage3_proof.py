"""Stage 3 proofs: LedgerProjector, StateMachine, IdAllocator.

Covers the eight required checks:
  1. Replaying the same events twice yields byte-identical ledger.json.
  2. Deleting ledger.json and rebuilding from events produces the same bytes.
  3. Entity arrays in the ledger are sorted by id ascending.
  4. OPERATION_FAILED / PROPOSAL_REJECTED / MODEL_RESPONSE_RECORDED(accepted false)
     do not mutate the projection.
  5. rejected -> locked raises an explicit illegal-transition error, state unchanged.
  6. A locked assumption cannot be overwritten except through revised.
  7. IdAllocator mints monotonic IDs per prefix and records the ref_map mapping.
  8. IdAllocator rejects duplicate temp handles and durable IDs in creation proposals.
"""

from __future__ import annotations

import pytest

from interrogation_harness import canonical
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.ids import (
    DurableIdInCreationError,
    DuplicateTempHandleError,
    IdAllocator,
    UnknownTempHandleError,
)
from interrogation_harness.projection import LedgerProjector, ProjectionError
from interrogation_harness.session_store import SessionStore
from interrogation_harness.state_machine import IllegalTransition, StateMachine

TS = "2026-01-01T00:00:00Z"
SID = "sess_demo"


def _log(tmp_path) -> EventLog:
    store = SessionStore(tmp_path / "sessions", SID)
    store.create()
    return EventLog(store)


def _append(log, event_type, payload, n, *, actor=Actor.HARNESS, ref_map=None):
    return log.append(
        event_type=event_type,
        actor=actor,
        session_id=SID,
        correlation_id=f"op-{n}",
        idempotency_key=f"k-{n}",
        timestamp=TS,
        payload=payload,
        ref_map=ref_map,
    )


def _seed_core(log) -> None:
    """A small but representative event sequence."""
    _append(log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
    _append(log, EventType.SOURCE_ADDED, {"content_hash": "abc123"}, 1)
    # Created out of id order on purpose to exercise array sorting.
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0002",
            "statement": "second",
            "status": "candidate",
            "source_type": "model_inferred",
            "blast_radius": "medium",
            "downstream_impact": "d",
            "risk_if_wrong": "r",
        },
        2,
    )
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0001",
            "statement": "first",
            "status": "provisional",
            "source_type": "user_stated",
            "source_excerpt": "first",
            "source_excerpt_verified": True,
            "blast_radius": "high",
            "downstream_impact": "d",
            "risk_if_wrong": "r",
        },
        3,
    )
    _append(
        log,
        EventType.WORK_ITEM_CREATED,
        {
            "id": "W-0001",
            "kind": "resolve_assumption",
            "status": "open",
            "question": "is the first true?",
            "why_it_matters": "w",
            "what_breaks_if_wrong": "b",
            "blast_radius": "high",
            "blocks_closure": True,
            "target_entity": "A-0001",
            "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
        },
        4,
    )
    _append(
        log,
        EventType.WORK_ITEM_STATUS_CHANGED,
        {"id": "W-0001", "from": "open", "to": "active", "reason": "asked"},
        5,
    )
    _append(
        log,
        EventType.ASSUMPTION_TRANSITIONED,
        {
            "id": "A-0001",
            "from": "provisional",
            "to": "locked",
            "reason": "user confirmed",
            "user_answer_event": "E-0099",
        },
        6,
    )


def test_rebuild_is_byte_identical_and_arrays_sorted(tmp_path):
    log = _log(tmp_path)
    store = log.store
    _seed_core(log)

    events = log.read_events()
    ledger_a = LedgerProjector().project(events)
    store.write_ledger(ledger_a)
    bytes_first = store.ledger_path.read_bytes()

    # Proof 3: arrays sorted by id ascending.
    assert [a["id"] for a in ledger_a["assumptions"]] == ["A-0001", "A-0002"]

    # Proof 2: delete and rebuild from events produces the same bytes.
    store.delete_ledger()
    assert not store.ledger_exists()
    ledger_b = LedgerProjector().project(log.read_events())
    store.write_ledger(ledger_b)
    bytes_second = store.ledger_path.read_bytes()
    assert bytes_first == bytes_second

    # Proof 1: replaying the same events twice yields identical serialization.
    assert canonical.dumps_ledger(ledger_a) == canonical.dumps_ledger(ledger_b)

    # The locked assumption recorded its answer event and stayed user_stated.
    locked = next(a for a in ledger_a["assumptions"] if a["id"] == "A-0001")
    assert locked["status"] == "locked"
    assert locked["user_answer_events"] == ["E-0099"]
    assert ledger_a["source_hash"] == "abc123"


def test_noop_events_do_not_mutate(tmp_path):
    log = _log(tmp_path)
    _seed_core(log)
    baseline = LedgerProjector().project(log.read_events())

    # Proof 4: append failure / rejection / non-accepted model response.
    _append(log, EventType.OPERATION_FAILED, {"retryable": True}, 7)
    _append(
        log,
        EventType.PROPOSAL_REJECTED,
        {"reason": "illegal", "rejected_proposal": {}},
        8,
    )
    _append(
        log,
        EventType.MODEL_RESPONSE_RECORDED,
        {"accepted": False, "validation_errors": ["x"], "job": "interpret_user_answer"},
        9,
    )
    after = LedgerProjector().project(log.read_events())
    assert after == baseline


def test_rejected_to_locked_is_illegal(tmp_path):
    # Direct check on the state machine.
    with pytest.raises(IllegalTransition):
        StateMachine.check("assumption", "rejected", "locked")
    with pytest.raises(IllegalTransition):
        StateMachine.check("assumption", "rejected", "provisional")
    with pytest.raises(IllegalTransition):
        StateMachine.check("assumption", "locked", "rejected")

    log = _log(tmp_path)
    _append(log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
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
    good = LedgerProjector().project(log.read_events())
    assert good["assumptions"][0]["status"] == "rejected"

    # Proof 5: an illegal rejected -> locked event makes the fold raise; the
    # projection built from the valid prefix is unchanged.
    _append(
        log,
        EventType.ASSUMPTION_TRANSITIONED,
        {"id": "A-0001", "from": "rejected", "to": "locked", "reason": "no"},
        3,
    )
    with pytest.raises(IllegalTransition):
        LedgerProjector().project(log.read_events())


def test_locked_assumption_only_changes_through_revised(tmp_path):
    log = _log(tmp_path)
    _append(log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
    _append(
        log,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0001",
            "statement": "original",
            "status": "provisional",
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
        {"id": "A-0001", "from": "provisional", "to": "locked", "reason": "ok"},
        2,
    )

    # locked -> revised is the only legal change and preserves the prior statement.
    _append(
        log,
        EventType.ASSUMPTION_TRANSITIONED,
        {
            "id": "A-0001",
            "from": "locked",
            "to": "revised",
            "reason": "new info",
            "prior_statement": "original",
            "new_statement": "updated",
        },
        3,
    )
    ledger = LedgerProjector().project(log.read_events())
    revised = ledger["assumptions"][0]
    assert revised["status"] == "revised"
    assert revised["statement"] == "updated"
    assert revised["revision_history"] == [
        {
            "event_id": "E-0004",
            "prior_statement": "original",
            "new_statement": "updated",
        }
    ]

    # Proof 6: any non-revised overwrite of a locked assumption is illegal. Build a
    # fresh log in a separate session that stops at locked, then attempt
    # locked -> rejected.
    log2 = EventLog(SessionStore(tmp_path / "sessions2", "s2"))
    log2.store.create()
    log2.append(
        event_type=EventType.SESSION_CREATED,
        actor=Actor.HARNESS,
        session_id="s2",
        correlation_id="op-0",
        idempotency_key="k-0",
        timestamp=TS,
        payload={"session_id": "s2"},
    )
    log2.append(
        event_type=EventType.ASSUMPTION_CREATED,
        actor=Actor.HARNESS,
        session_id="s2",
        correlation_id="op-1",
        idempotency_key="k-1",
        timestamp=TS,
        payload={
            "id": "A-0001",
            "statement": "x",
            "status": "locked",
            "source_type": "model_inferred",
            "blast_radius": "low",
            "downstream_impact": "d",
            "risk_if_wrong": "r",
        },
    )
    log2.append(
        event_type=EventType.ASSUMPTION_TRANSITIONED,
        actor=Actor.HARNESS,
        session_id="s2",
        correlation_id="op-2",
        idempotency_key="k-2",
        timestamp=TS,
        payload={"id": "A-0001", "from": "locked", "to": "rejected", "reason": "no"},
    )
    with pytest.raises(IllegalTransition):
        LedgerProjector().project(log2.read_events())


def test_single_active_work_item_enforced(tmp_path):
    log = _log(tmp_path)
    _append(log, EventType.SESSION_CREATED, {"session_id": SID}, 0)
    for n, wid in ((1, "W-0001"), (2, "W-0002")):
        _append(
            log,
            EventType.WORK_ITEM_CREATED,
            {
                "id": wid,
                "kind": "clarify",
                "status": "open",
                "question": "q",
                "why_it_matters": "w",
                "what_breaks_if_wrong": "b",
                "blast_radius": "low",
                "blocks_closure": False,
            },
            n,
        )
    _append(
        log,
        EventType.WORK_ITEM_STATUS_CHANGED,
        {"id": "W-0001", "from": "open", "to": "active", "reason": "a"},
        3,
    )
    _append(
        log,
        EventType.WORK_ITEM_STATUS_CHANGED,
        {"id": "W-0002", "from": "open", "to": "active", "reason": "b"},
        4,
    )
    with pytest.raises(ProjectionError):
        LedgerProjector().project(log.read_events())


def test_id_allocator_monotonic_and_ref_map():
    allocator = IdAllocator()  # empty session
    ref_map = allocator.allocate(
        ["tmp_assumption_1", "tmp_assumption_2", "tmp_work_1"]
    )
    # Proof 7: monotonic per prefix, mapping recorded.
    assert ref_map == {
        "tmp_assumption_1": "A-0001",
        "tmp_assumption_2": "A-0002",
        "tmp_work_1": "W-0001",
    }

    # Seeding from accepted events (ref_map) continues monotonically.
    events = [{"event_type": "ASSUMPTION_CREATED", "ref_map": ref_map}]
    continued = IdAllocator.from_events(events)
    assert continued.peek_next("A") == "A-0003"
    assert continued.allocate(["tmp_assumption_9"]) == {"tmp_assumption_9": "A-0003"}

    # Seeding from a ledger projection also works.
    ledger = {"assumptions": [{"id": "A-0005"}], "work_items": [{"id": "W-0002"}]}
    from_ledger = IdAllocator.from_ledger(ledger)
    assert from_ledger.peek_next("A") == "A-0006"
    assert from_ledger.peek_next("W") == "W-0003"


def test_id_allocator_rejects_bad_creation_input():
    allocator = IdAllocator()
    # Proof 8: duplicate temp handle.
    with pytest.raises(DuplicateTempHandleError):
        allocator.allocate(["tmp_assumption_1", "tmp_assumption_1"])
    # Durable ID where only a temp handle is allowed.
    with pytest.raises(DurableIdInCreationError):
        IdAllocator().allocate(["A-0001"])
    # Unknown handle form.
    with pytest.raises(UnknownTempHandleError):
        IdAllocator().allocate(["assumption_1"])
    # The scanning helper also rejects durable IDs in creation fields.
    with pytest.raises(DurableIdInCreationError):
        IdAllocator.assert_no_durable_ids(["tmp_work_1", "T-0003"])
