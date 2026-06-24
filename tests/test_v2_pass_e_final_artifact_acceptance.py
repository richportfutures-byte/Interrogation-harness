"""V2 Pass 3: final artifact, canonical sample, and end-to-end acceptance."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from interrogation_harness import canonical
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.model import DeterministicMockModel, MockScenario, ModelJob
from interrogation_harness.operations import HarnessOperations
from interrogation_harness.session_store import SessionStore
from interrogation_harness.validation import ModelContractValidator

TS = "2026-01-01T00:00:00Z"
SOURCE = "Payments require idempotency keys.\n"


class _RawModel:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def complete(self, request, *, scenario=None):
        return self.raw


def _raw(obj: dict) -> str:
    return canonical.dumps_event_line(obj)


def _v2_complete_session(tmp_path) -> HarnessOperations:
    ops = HarnessOperations(tmp_path / "sessions", "v2_complete", now=lambda: TS)
    ops.create_session(
        protocol_version="2.0.0",
        session_frame={
            "topic": "payment retries",
            "downstream_use": "implementation",
            "closure_standard": "all blockers resolved",
            "input_mode": "unstructured",
        },
    )
    ops.add_source(SOURCE)
    assert ops.run_intake().accepted
    ops.ask_next()
    assert ops.answer("confirm").accepted
    assert ops.run_blind_spot_audit()["accepted"]
    return ops


def test_v2_final_artifact_uses_protocol_sections_and_closure_status(tmp_path):
    ops = _v2_complete_session(tmp_path)

    result = ops.generate_artifact()
    text = ops.store.artifact_path.read_text(encoding="utf-8")
    artifact_event = [
        event
        for event in ops.event_log.read_events()
        if event["event_type"] == EventType.ARTIFACT_GENERATED.value
    ][-1]

    assert result["accepted"] is True
    assert text.startswith("# Premise Control Artifact V2\n")
    for section in (
        "## Scope and Objective",
        "## Closure Status",
        "## Locked Assumptions",
        "## Provisional and Unconfirmed Assumptions",
        "## Revision Log",
        "## Open Risks and Undecidable Assumptions",
        "## Authority Map",
        "## Failure-Mode Declarations",
        "## Definitions for Critical Terms",
        "## Items Explicitly Excluded From Scope",
        "## Validation Actions Still Required",
        "## Downstream Builder Instructions",
    ):
        assert section in text
    assert "Topic: payment retries" in text
    assert "Blind-spot audit status: complete" in text
    assert "A-0001: Payments require idempotency keys." in text
    assert "Evidence: verified_user_stated" in text
    assert artifact_event["payload"]["closure_status"] == {
        "mode": "open",
        "complete": True,
        "force_closed_event": None,
    }


def test_v2_artifact_validation_rejects_omitted_unresolved_blocker(tmp_path):
    ops = HarnessOperations(tmp_path / "sessions", "bad_v2_artifact", now=lambda: TS)
    ops.create_session(protocol_version="2.0.0")
    _append(
        ops,
        EventType.ASSUMPTION_CREATED,
        {
            "id": "A-0001",
            "statement": "Payments require idempotency keys.",
            "status": "locked",
            "source_type": "user_stated",
            "source_excerpt": "Payments require idempotency keys.",
            "source_excerpt_verified": True,
            "blast_radius": "high",
            "downstream_impact": "Payment retries",
            "risk_if_wrong": "Duplicate charges",
            "evidence_status": "verified_user_stated",
            "premise_origin": "intake",
        },
        1,
    )
    _append(
        ops,
        EventType.WORK_ITEM_CREATED,
        {
            "id": "W-0001",
            "kind": "clarify",
            "status": "open",
            "question": "Who owns retry authority?",
            "why_it_matters": "Authority controls closure.",
            "what_breaks_if_wrong": "Retries may use the wrong owner.",
            "blast_radius": "high",
            "blocks_closure": True,
            "target_entity": "A-0001",
            "gap_type": "authority_ownership",
        },
        2,
    )
    _append(ops, EventType.AUDIT_RUN, {"audit_type": "blind_spot", "findings_summary": {}}, 3)
    force_event = _append(ops, EventType.FORCE_CLOSED, {"reason": "test"}, 4)
    ops.rebuild_ledger()
    bad_output = {
        "artifact_markdown": (
            "# Premise Control Artifact V2\n\n"
            "## Locked Assumptions\n\n"
            "- A-0001: Payments require idempotency keys. Status: locked.\n"
        ),
        "blocking_warnings": [],
        "open_risk_register": [],
        "traceability_summary": [
            {"entity_id": "A-0001", "source": "user_stated", "verified": True}
        ],
        "closure_status": {
            "mode": "force_closed",
            "complete": False,
            "force_closed_event": force_event["event_id"],
        },
    }

    result = ModelContractValidator(
        ops.event_log,
        _RawModel(_raw(bad_output)),
        ops.projector,
    ).run(
        ModelJob.ARTIFACT_GENERATION,
        session_id=ops.session_id,
        correlation_id="bad-artifact",
        idempotency_key="bad-artifact",
        timestamp=TS,
        request_payload={"projection": ops.ledger()},
    )

    assert not result.accepted
    assert "omits unresolved blocker" in result.errors[0]


def test_v2_sample_builder_is_deterministic_and_end_to_end(tmp_path):
    root = tmp_path / "sessions"
    session_id = "v2_sample_session"
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_v2_sample_session.py"

    subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--session-id", session_id],
        check=True,
        text=True,
        capture_output=True,
    )
    store = SessionStore(root, session_id)
    first = _session_bytes(store)

    subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--session-id", session_id],
        check=True,
        text=True,
        capture_output=True,
    )
    second = _session_bytes(store)
    ledger = store.read_ledger()
    text = store.artifact_path.read_text(encoding="utf-8")

    assert second == first
    assert ledger["protocol_version"] == "2.0.0"
    assert ledger["intake_status"] == "complete"
    assert ledger["blind_spot_audit_status"] == "complete"
    assert ledger["force_closed"] is True
    assert "# Premise Control Artifact V2" in text
    assert "Closure is controlled incomplete closure" in text
    assert "Feed gap reconnect behavior requires external validation" in text
    assert any(item.get("premise_origin") == "blind_spot" for item in ledger["assumptions"])


def test_v2_artifact_mock_scenarios_are_available():
    model = DeterministicMockModel()

    normal = model.complete(
        _request(ModelJob.ARTIFACT_GENERATION),
        scenario=MockScenario.ARTIFACT_GENERATION_V2.value,
    )
    incomplete = model.complete(
        _request(ModelJob.ARTIFACT_GENERATION),
        scenario=MockScenario.ARTIFACT_FORCE_CLOSED_INCOMPLETE.value,
    )

    assert canonical.loads(normal)["closure_status"]["complete"] is True
    assert canonical.loads(incomplete)["closure_status"]["complete"] is False


def _append(ops: HarnessOperations, event_type: EventType, payload: dict, n: int) -> dict:
    return ops.event_log.append(
        event_type=event_type,
        actor=Actor.HARNESS,
        session_id=ops.session_id,
        correlation_id=f"seed-{n}",
        idempotency_key=f"seed-{n}",
        timestamp=TS,
        payload=payload,
    )


def _request(job: ModelJob):
    from interrogation_harness.model import ModelRequest

    return ModelRequest.from_payload(job, {"session_id": "demo"})


def _session_bytes(store: SessionStore) -> dict[str, bytes]:
    return {
        "source": store.source_path.read_bytes(),
        "events": store.events_path.read_bytes(),
        "ledger": store.ledger_path.read_bytes(),
        "artifact": store.artifact_path.read_bytes(),
    }
