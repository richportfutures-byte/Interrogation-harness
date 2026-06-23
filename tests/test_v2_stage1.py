"""V2 Stage 1: protocol-version activation and deterministic V2 ledger projection.

Scope of this stage (V2 Implementation Spec, stages 1 and 2):
  - create-session activates V2 and stores protocol_version / session_frame.
  - The projector emits the four V2 ledger fields, deterministically, and only for V2
    sessions. V1 sessions keep their exact V1 ledger shape (Decision D3).

No V2 model jobs, run-intake, or blind-spot audit exist yet, so the intake and
blind-spot signals are exercised with synthetic events (the same payloads later stages
will produce).
"""

from __future__ import annotations

from interrogation_harness import canonical
from interrogation_harness.cli import main
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.model import DeterministicMockModel
from interrogation_harness.operations import HarnessOperations
from interrogation_harness.session_store import SessionStore

TS = "2026-01-01T00:00:00Z"
SID = "v2_stage1"
_V2_LEDGER_FIELDS = (
    "protocol_version",
    "session_frame",
    "intake_status",
    "blind_spot_audit_status",
)


def _ops(tmp_path, session_id: str = SID) -> HarnessOperations:
    return HarnessOperations(
        tmp_path / "sessions",
        session_id,
        model=DeterministicMockModel(),
        now=lambda: TS,
    )


def _append(ops, event_type, payload, n, *, correlation=None, actor=Actor.HARNESS):
    return ops.event_log.append(
        event_type=event_type,
        actor=actor,
        session_id=ops.session_id,
        correlation_id=correlation or f"seed-{n}",
        idempotency_key=f"seed-key-{n}",
        timestamp=TS,
        payload=payload,
    )


def _session_created(ops, n, payload):
    return _append(ops, EventType.SESSION_CREATED, payload, n)


# -- V1 default path is unchanged ------------------------------------------


def test_v1_default_create_session_emits_no_v2_fields(tmp_path):
    ops = _ops(tmp_path)
    ledger = ops.create_session()
    for field in _V2_LEDGER_FIELDS:
        assert field not in ledger
    created = ops.event_log.read_events()[0]
    assert created["payload"] == {"session_id": SID}
    assert "ref_map" not in created


def test_v1_ledger_rebuild_is_byte_identical_without_v2_fields(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session()
    first = ops.store.ledger_path.read_bytes()
    ops.store.delete_ledger()
    ops.rebuild_ledger()
    assert ops.store.ledger_path.read_bytes() == first
    assert b"protocol_version" not in first


# -- V2 activation at creation ---------------------------------------------


def test_v2_create_session_records_protocol_version(tmp_path):
    ops = _ops(tmp_path)
    ledger = ops.create_session(protocol_version="2.0.0")
    created = ops.event_log.read_events()[0]
    assert created["payload"]["protocol_version"] == "2.0.0"
    assert ledger["protocol_version"] == "2.0.0"
    assert ledger["intake_status"] == "not_required"  # no source yet
    assert ledger["blind_spot_audit_status"] == "not_run"
    assert ledger["session_frame"] == {
        "topic": None,
        "downstream_use": None,
        "closure_standard": None,
        "input_mode": None,
    }


def test_v2_session_frame_stored_and_projected_at_creation(tmp_path):
    ops = _ops(tmp_path)
    frame = {
        "topic": "payment retries",
        "downstream_use": "implementation",
        "closure_standard": "all high blast radius locked",
        "input_mode": "unstructured",
    }
    ledger = ops.create_session(protocol_version="2.0.0", session_frame=frame)
    assert ledger["session_frame"] == frame
    assert ops.event_log.read_events()[0]["payload"]["session_frame"] == frame


def test_v2_session_with_source_requires_intake(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session(protocol_version="2.0.0")
    ledger = ops.add_source("Some unstructured narrative about payments.\n")
    assert ledger["protocol_version"] == "2.0.0"
    assert ledger["intake_status"] == "required"
    assert ledger["blind_spot_audit_status"] == "not_run"


# -- V2 inference from accepted intake / blind-spot events -----------------


def test_accepted_intake_response_infers_v2_and_completes_intake(tmp_path):
    ops = _ops(tmp_path)
    ops.store.create()
    # A V1-style create (no protocol_version), upgraded by an accepted intake response.
    _session_created(ops, 0, {"session_id": SID})
    _append(ops, EventType.SOURCE_ADDED, {"content_hash": "abc"}, 1)
    frame = {
        "topic": "payments",
        "downstream_use": "build",
        "closure_standard": "locks",
        "input_mode": "mixed",
    }
    _append(
        ops,
        EventType.MODEL_RESPONSE_RECORDED,
        {
            "job": "intake_unstructured_input",
            "accepted": True,
            "validation_errors": [],
            "raw_output": "{}",
            "session_frame": frame,
        },
        2,
        correlation="intake-1",
        actor=Actor.MODEL,
    )
    _append(
        ops,
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
        3,
        correlation="intake-1",
    )
    ledger = ops.ledger()
    assert ledger["protocol_version"] == "2.0.0"  # inferred, not explicit
    assert ledger["session_frame"] == frame  # from the intake response
    assert ledger["intake_status"] == "complete"


def test_session_created_frame_wins_over_intake_frame(tmp_path):
    ops = _ops(tmp_path)
    ops.store.create()
    created_frame = {
        "topic": "from-create",
        "downstream_use": None,
        "closure_standard": None,
        "input_mode": "structured",
    }
    _session_created(ops, 0, {"session_id": SID, "session_frame": created_frame})
    _append(ops, EventType.SOURCE_ADDED, {"content_hash": "abc"}, 1)
    _append(
        ops,
        EventType.MODEL_RESPONSE_RECORDED,
        {
            "job": "intake_unstructured_input",
            "accepted": True,
            "session_frame": {
                "topic": "from-intake",
                "downstream_use": "x",
                "closure_standard": "y",
                "input_mode": "mixed",
            },
        },
        2,
        correlation="intake-1",
        actor=Actor.MODEL,
    )
    assert ops.ledger()["session_frame"] == created_frame


def test_blind_spot_audit_infers_v2_and_completes_audit(tmp_path):
    ops = _ops(tmp_path)
    ops.store.create()
    _session_created(ops, 0, {"session_id": SID})
    _append(
        ops,
        EventType.AUDIT_RUN,
        {"audit_type": "blind_spot", "findings_summary": {}},
        1,
    )
    ledger = ops.ledger()
    assert ledger["protocol_version"] == "2.0.0"
    assert ledger["blind_spot_audit_status"] == "complete"


# -- rejected / failed signals never upgrade or complete -------------------


def test_rejected_intake_does_not_upgrade_v1_session(tmp_path):
    ops = _ops(tmp_path)
    ops.store.create()
    _session_created(ops, 0, {"session_id": SID})
    _append(ops, EventType.SOURCE_ADDED, {"content_hash": "abc"}, 1)
    _append(
        ops,
        EventType.MODEL_RESPONSE_RECORDED,
        {"job": "intake_unstructured_input", "accepted": False, "validation_errors": ["bad"]},
        2,
        correlation="intake-1",
        actor=Actor.MODEL,
    )
    ledger = ops.ledger()
    # Not accepted, so no upgrade: the session stays V1 and emits no V2 fields.
    for field in _V2_LEDGER_FIELDS:
        assert field not in ledger


def test_v2_session_rejected_intake_stays_required(tmp_path):
    ops = _ops(tmp_path)
    ops.create_session(protocol_version="2.0.0")
    ops.add_source("narrative\n")
    _append(
        ops,
        EventType.MODEL_RESPONSE_RECORDED,
        {"job": "intake_unstructured_input", "accepted": False, "validation_errors": ["bad"]},
        5,
        correlation="intake-1",
        actor=Actor.MODEL,
    )
    assert ops.ledger()["intake_status"] == "required"


# -- CLI activation --------------------------------------------------------


def test_cli_create_session_protocol_version(tmp_path, capsys):
    root = tmp_path / "sessions"
    assert main(["--root", str(root), "create-session", "cli_v2", "--protocol-version", "2.0.0"]) == 0
    capsys.readouterr()
    store = SessionStore(root, "cli_v2")
    created = EventLog(store).read_events()[0]
    assert created["payload"]["protocol_version"] == "2.0.0"
    ledger = canonical.loads(store.ledger_path.read_text(encoding="utf-8"))
    assert ledger["protocol_version"] == "2.0.0"


def test_cli_default_create_session_is_v1(tmp_path, capsys):
    root = tmp_path / "sessions"
    assert main(["--root", str(root), "create-session", "cli_v1"]) == 0
    capsys.readouterr()
    store = SessionStore(root, "cli_v1")
    created = EventLog(store).read_events()[0]
    assert created["payload"] == {"session_id": "cli_v1"}
    ledger = canonical.loads(store.ledger_path.read_text(encoding="utf-8"))
    assert "protocol_version" not in ledger
