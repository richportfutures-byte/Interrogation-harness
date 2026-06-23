"""Stage 1 minimal import check: the type/schema layer must import cleanly.

This is intentionally shallow. It confirms the modules import and that a few closed
value sets carry their canonical string values. Behavioral tests arrive in later stages.
"""

from __future__ import annotations


def test_records_module_imports():
    from interrogation_harness import records

    assert records.AssumptionStatus.LOCKED.value == "locked"
    assert records.SourceType.USER_STATED.value == "user_stated"
    assert records.WorkItemKind.RESOLVE_ASSUMPTION.value == "resolve_assumption"
    assert records.WorkItemStatus.ACTIVE.value == "active"
    assert records.AnswerClass.CONFIRM.value == "confirm"


def test_records_dataclasses_construct():
    from interrogation_harness import records

    work_item = records.WorkItem(
        id="W-0001",
        kind=records.WorkItemKind.RESOLVE_ASSUMPTION,
        status=records.WorkItemStatus.OPEN,
        question="q",
        why_it_matters="w",
        what_breaks_if_wrong="b",
        blast_radius=records.BlastRadius.HIGH,
        blocks_closure=True,
        created_event="E-0002",
        updated_event="E-0002",
    )
    assert work_item.answer_options == []
    assert work_item.target_entity is None


def test_events_module_imports():
    from interrogation_harness import events

    assert events.SCHEMA_VERSION == "1.0.0"
    assert events.Actor.HARNESS.value == "harness"
    assert events.EventType.SESSION_CREATED.value == "SESSION_CREATED"
    # The closed event-type set has exactly 21 members (Section 6.2).
    assert len(list(events.EventType)) == 21


def test_event_envelope_constructs():
    from interrogation_harness import events

    event = events.Event(
        event_id="E-0001",
        session_id="s",
        timestamp="2026-01-01T00:00:00Z",
        event_type=events.EventType.SESSION_CREATED,
        actor=events.Actor.HARNESS,
        correlation_id="c",
        idempotency_key="k",
    )
    assert event.schema_version == "1.0.0"
    assert event.payload == {}
    assert event.ref_map is None
