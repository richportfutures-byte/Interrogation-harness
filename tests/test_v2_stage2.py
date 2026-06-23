"""V2 Stage 2: optional premise fields on records, projection, and serialization.

These tests drive the projector directly with event dicts (the projection focus of this
stage). They prove the V2 entity fields are carried into projected records when present,
omitted when null or empty, validated for enum legality, and absent for V1 records.
"""

from __future__ import annotations

import pytest

from interrogation_harness.projection import LedgerProjector, ProjectionError

_ASSUMPTION_V2 = ("intake_label", "premise_origin", "evidence_status", "depends_on")
_WORK_ITEM_V2 = (
    "derived_question_label",
    "gap_type",
    "source_assumption_ids",
    "blocking_reason",
)


def _ev(event_id: str, event_type: str, payload: dict, **extra) -> dict:
    event = {"event_id": event_id, "event_type": event_type, "payload": payload}
    event.update(extra)
    return event


def _assumption_payload(**overrides) -> dict:
    payload = {
        "id": "A-0001",
        "statement": "x",
        "status": "candidate",
        "source_type": "model_inferred",
        "blast_radius": "low",
        "downstream_impact": "d",
        "risk_if_wrong": "r",
    }
    payload.update(overrides)
    return payload


def _work_item_payload(**overrides) -> dict:
    payload = {
        "id": "W-0001",
        "kind": "resolve_assumption",
        "status": "open",
        "question": "q",
        "why_it_matters": "w",
        "what_breaks_if_wrong": "b",
        "blast_radius": "high",
        "blocks_closure": True,
    }
    payload.update(overrides)
    return payload


def _project(*events: dict) -> dict:
    return LedgerProjector().project(list(events))


def test_v1_records_have_no_v2_fields_when_absent():
    ledger = _project(
        _ev("E-0001", "SESSION_CREATED", {"session_id": "s"}),
        _ev("E-0002", "ASSUMPTION_CREATED", _assumption_payload()),
        _ev("E-0003", "WORK_ITEM_CREATED", _work_item_payload()),
    )
    assumption = ledger["assumptions"][0]
    work_item = ledger["work_items"][0]
    for field in _ASSUMPTION_V2:
        assert field not in assumption
    for field in _WORK_ITEM_V2:
        assert field not in work_item
    # V1 session: no ledger-level V2 fields either.
    assert "protocol_version" not in ledger


def test_v2_assumption_carries_non_null_fields():
    ledger = _project(
        _ev("E-0001", "SESSION_CREATED", {"session_id": "s", "protocol_version": "2.0.0"}),
        _ev(
            "E-0002",
            "ASSUMPTION_CREATED",
            _assumption_payload(
                intake_label="CA-01",
                premise_origin="intake",
                evidence_status="model_inferred",
                depends_on=["A-0002"],
            ),
        ),
    )
    assumption = ledger["assumptions"][0]
    assert assumption["intake_label"] == "CA-01"
    assert assumption["premise_origin"] == "intake"
    assert assumption["evidence_status"] == "model_inferred"
    assert assumption["depends_on"] == ["A-0002"]
    assert ledger["protocol_version"] == "2.0.0"


def test_v2_work_item_carries_non_null_fields():
    ledger = _project(
        _ev("E-0001", "SESSION_CREATED", {"session_id": "s", "protocol_version": "2.0.0"}),
        _ev(
            "E-0002",
            "WORK_ITEM_CREATED",
            _work_item_payload(
                derived_question_label="DQ-01",
                gap_type="failure_mode",
                source_assumption_ids=["A-0001"],
                blocking_reason="high blast radius",
            ),
        ),
    )
    work_item = ledger["work_items"][0]
    assert work_item["derived_question_label"] == "DQ-01"
    assert work_item["gap_type"] == "failure_mode"
    assert work_item["source_assumption_ids"] == ["A-0001"]
    assert work_item["blocking_reason"] == "high blast radius"


def test_empty_lists_are_omitted_from_serialized_records():
    ledger = _project(
        _ev("E-0001", "SESSION_CREATED", {"session_id": "s", "protocol_version": "2.0.0"}),
        _ev(
            "E-0002",
            "ASSUMPTION_CREATED",
            _assumption_payload(premise_origin="intake", depends_on=[]),
        ),
        _ev(
            "E-0003",
            "WORK_ITEM_CREATED",
            _work_item_payload(gap_type="failure_mode", source_assumption_ids=[]),
        ),
    )
    assumption = ledger["assumptions"][0]
    work_item = ledger["work_items"][0]
    # Empty lists dropped; a present scalar stays.
    assert "depends_on" not in assumption
    assert assumption["premise_origin"] == "intake"
    assert "source_assumption_ids" not in work_item
    assert work_item["gap_type"] == "failure_mode"


def test_invalid_premise_origin_raises():
    with pytest.raises(ProjectionError):
        _project(
            _ev("E-0001", "SESSION_CREATED", {"session_id": "s", "protocol_version": "2.0.0"}),
            _ev("E-0002", "ASSUMPTION_CREATED", _assumption_payload(premise_origin="bogus")),
        )


def test_invalid_evidence_status_raises():
    with pytest.raises(ProjectionError):
        _project(
            _ev("E-0001", "SESSION_CREATED", {"session_id": "s", "protocol_version": "2.0.0"}),
            _ev("E-0002", "ASSUMPTION_CREATED", _assumption_payload(evidence_status="nope")),
        )


def test_invalid_gap_type_raises():
    with pytest.raises(ProjectionError):
        _project(
            _ev("E-0001", "SESSION_CREATED", {"session_id": "s", "protocol_version": "2.0.0"}),
            _ev("E-0002", "WORK_ITEM_CREATED", _work_item_payload(gap_type="invalid_gap")),
        )
