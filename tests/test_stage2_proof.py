"""Stage 2 proof: canonical serialization, SessionStore, and EventLog.

Demonstrates the five required points:
  1. an event appends,
  2. it reads back,
  3. it serializes byte-identically per Section 9,
  4. a failed or rejected event with an idempotency key does not mark the key accepted,
  5. a later accepted event under that same key can be recorded.
"""

from __future__ import annotations

from interrogation_harness import canonical
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.session_store import SessionStore

TS = "2026-01-01T00:00:00Z"
SID = "sess_demo"


def _log(tmp_path) -> EventLog:
    store = SessionStore(tmp_path / "sessions", SID)
    store.create()
    return EventLog(store)


def test_append_and_read_back(tmp_path):
    log = _log(tmp_path)
    recorded = log.append(
        event_type=EventType.SESSION_CREATED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-1",
        idempotency_key="k-session",
        timestamp=TS,
        payload={"session_id": SID},
    )
    # 1. appends with a minted sequential id.
    assert recorded["event_id"] == "E-0001"
    # 2. reads back identically.
    events = log.read_events()
    assert events == [recorded]


def test_byte_identical_serialization(tmp_path):
    log = _log(tmp_path)
    recorded = log.append(
        event_type=EventType.SESSION_CREATED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-1",
        idempotency_key="k-session",
        timestamp=TS,
        payload={"session_id": SID},
    )
    lines = log.store.read_event_lines()
    assert len(lines) == 1
    line = lines[0]

    # 3. compact, sorted keys, no spaces after separators, stable round trip.
    assert line == canonical.dumps_event_line(recorded)
    assert ", " not in line
    assert ": " not in line
    assert line.index('"actor"') < line.index('"event_id"')  # keys sorted
    assert canonical.dumps_event_line(canonical.loads(line)) == line

    # ledger format: two space indent, sorted keys at every level, arrays unsorted,
    # single trailing newline, no trailing whitespace.
    log.store.write_ledger({"b": 1, "a": {"d": 2, "c": [3, 1]}})
    ledger_text = log.store.ledger_path.read_text(encoding="utf-8")
    assert ledger_text == (
        "{\n"
        '  "a": {\n'
        '    "c": [\n'
        "      3,\n"
        "      1\n"
        "    ],\n"
        '    "d": 2\n'
        "  },\n"
        '  "b": 1\n'
        "}\n"
    )
    assert ledger_text.endswith("}\n")
    assert not any(line.endswith(" ") for line in ledger_text.split("\n"))


def test_idempotency_failed_then_rejected_does_not_accept(tmp_path):
    log = _log(tmp_path)
    key = "k-retry"

    # Transport failure under the key.
    log.append(
        event_type=EventType.OPERATION_FAILED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-2",
        idempotency_key=key,
        timestamp=TS,
        payload={"retryable": True},
    )
    # Second attempt: model output rejected (recorded false + proposal rejected).
    log.append(
        event_type=EventType.MODEL_RESPONSE_RECORDED,
        actor=Actor.MODEL,
        session_id=SID,
        correlation_id="op-3",
        idempotency_key=key,
        timestamp=TS,
        payload={"accepted": False, "validation_errors": ["bad enum"]},
    )
    log.append(
        event_type=EventType.PROPOSAL_REJECTED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-3",
        idempotency_key=key,
        timestamp=TS,
        payload={"reason": "illegal transition"},
    )

    # 4. the key is NOT accepted; it remains reusable.
    assert log.accepted_correlation(key) is None
    assert key not in log.idempotency_map()


def test_idempotency_later_accepted_under_same_key(tmp_path):
    log = _log(tmp_path)
    key = "k-retry"

    log.append(
        event_type=EventType.OPERATION_FAILED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-2",
        idempotency_key=key,
        timestamp=TS,
        payload={"retryable": True},
    )
    # Later successful attempt reuses the same key under a new correlation.
    log.append(
        event_type=EventType.MODEL_RESPONSE_RECORDED,
        actor=Actor.MODEL,
        session_id=SID,
        correlation_id="op-4",
        idempotency_key=key,
        timestamp=TS,
        payload={"accepted": True},
    )
    log.append(
        event_type=EventType.ASSUMPTION_CREATED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-4",
        idempotency_key=key,
        timestamp=TS,
        payload={"id": "A-0001", "statement": "x"},
        ref_map={"tmp_assumption_1": "A-0001"},
    )

    # 5. the accepted operation is now recorded for the key.
    assert log.accepted_correlation(key) == "op-4"

    # Failure and rejection records are preserved in the log.
    types = [event["event_type"] for event in log.read_events()]
    assert "OPERATION_FAILED" in types
    assert types.count("MODEL_RESPONSE_RECORDED") == 1
    # ref_map present only on the creating event.
    created = [e for e in log.read_events() if e["event_type"] == "ASSUMPTION_CREATED"][0]
    assert created["ref_map"] == {"tmp_assumption_1": "A-0001"}
    failed = [e for e in log.read_events() if e["event_type"] == "OPERATION_FAILED"][0]
    assert "ref_map" not in failed


def test_source_write_append_and_export(tmp_path):
    log = _log(tmp_path)
    store = log.store
    store.write_source("first line\n")
    store.append_source("second line\n")
    assert store.read_source() == "first line\nsecond line\n"

    log.append(
        event_type=EventType.SESSION_CREATED,
        actor=Actor.HARNESS,
        session_id=SID,
        correlation_id="op-1",
        idempotency_key="k-session",
        timestamp=TS,
        payload={},
    )
    exported = store.export(tmp_path / "out")
    names = sorted(p.name for p in exported)
    assert names == ["events.jsonl", "source.md"]
