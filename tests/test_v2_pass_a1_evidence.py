"""V2 Pass A.1: evidence_status finalization (Decision D6).

The ledger must never contain source_type model_inferred with evidence_status
verified_user_stated. evidence_status is harness-finalized after provenance, so a model
claim can never override final provenance.
"""

from __future__ import annotations

from interrogation_harness import canonical
from interrogation_harness.model import DeterministicMockModel, MockScenario
from interrogation_harness.operations import HarnessOperations

TS = "2026-01-01T00:00:00Z"
VERIFIABLE_EXCERPT = "Payments require idempotency keys."
SOURCE_WITH_EXCERPT = "Payments require idempotency keys.\n"
SOURCE_WITHOUT = "Unrelated project notes with no matching excerpt.\n"


class _RawModel:
    """Adapter that always returns one fixed raw output string."""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def complete(self, request, *, scenario=None):
        return self._raw


class _ScenarioModel:
    """Adapter that always returns one named scenario's raw output."""

    def __init__(self, scenario: MockScenario) -> None:
        self._scenario = scenario
        self._mock = DeterministicMockModel()

    def complete(self, request, *, scenario=None):
        return self._mock.complete(request, scenario=self._scenario.value)


def _assumption(handle: str, label: str, **over) -> dict:
    base = {
        "tmp_handle": handle,
        "intake_label": label,
        "statement": f"Statement {label}",
        "status": "candidate",
        "source_type": "model_inferred",
        "source_excerpt": None,
        "blast_radius": "medium",
        "downstream_impact": "impact",
        "risk_if_wrong": "risk",
        "evidence_status": "model_inferred",
    }
    base.update(over)
    return base


def _intake(assumptions: list[dict]) -> dict:
    return {
        "session_frame": {
            "topic": "t",
            "downstream_use": "d",
            "closure_standard": "c",
            "input_mode": "unstructured",
        },
        "assumptions": assumptions,
        "work_items": [],
        "risks": [],
        "terms": [],
        "decisions": [],
        "contradictions": [],
    }


def _run_raw_intake(tmp_path, intake: dict, source: str, session="ev"):
    ops = HarnessOperations(
        tmp_path / "sessions",
        session,
        model=_RawModel(canonical.dumps_event_line(intake)),
        now=lambda: TS,
    )
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(source)
    return ops, ops.run_intake()


def _assumptions(ops):
    return ops.ledger()["assumptions"]


def test_verified_user_stated_overrides_wrong_model_claim(tmp_path):
    # Model proposes "undecidable" for an excerpt that verifies; harness finalizes.
    intake = _intake(
        [
            _assumption(
                "tmp_assumption_1",
                "CA-01",
                source_type="user_stated",
                source_excerpt=VERIFIABLE_EXCERPT,
                evidence_status="undecidable",
            )
        ]
    )
    ops, result = _run_raw_intake(tmp_path, intake, SOURCE_WITH_EXCERPT)
    assert result.accepted
    first = _assumptions(ops)[0]
    assert first["source_type"] == "user_stated"
    assert first["source_excerpt_verified"] is True
    assert first["evidence_status"] == "verified_user_stated"


def test_unverifiable_user_stated_downgrades_evidence(tmp_path):
    intake = _intake(
        [
            _assumption(
                "tmp_assumption_1",
                "CA-01",
                source_type="user_stated",
                source_excerpt="A line that is not present in the source.",
                evidence_status="verified_user_stated",
            )
        ]
    )
    ops, result = _run_raw_intake(tmp_path, intake, SOURCE_WITHOUT)
    assert result.accepted
    first = _assumptions(ops)[0]
    assert first["source_type"] == "model_inferred"
    assert first["source_excerpt_verified"] is False
    assert first["evidence_status"] == "model_inferred"


def test_forbidden_combination_never_reaches_ledger(tmp_path):
    # Named adversarial scenario: model claims verified_user_stated, excerpt unverifiable.
    ops = HarnessOperations(
        tmp_path / "sessions",
        "ev_named",
        model=_ScenarioModel(MockScenario.INTAKE_UNVERIFIABLE_EXCERPT),
        now=lambda: TS,
    )
    ops.create_session(protocol_version="2.0.0")
    ops.add_source(SOURCE_WITHOUT)
    result = ops.run_intake()
    assert result.accepted
    accepted = next(
        e
        for e in ops.event_log.read_events()
        if e["event_type"] == "MODEL_RESPONSE_RECORDED" and e["payload"].get("accepted")
    )
    # The model really did propose the forbidden value...
    assert "verified_user_stated" in accepted["payload"]["raw_output"]
    # ...but it never reaches the ledger.
    for assumption in ops.ledger()["assumptions"]:
        assert not (
            assumption.get("source_type") == "model_inferred"
            and assumption.get("evidence_status") == "verified_user_stated"
        )
    first = ops.ledger()["assumptions"][0]
    assert first["source_type"] == "model_inferred"
    assert first["evidence_status"] == "model_inferred"


def test_model_inferred_preserves_explicit_special_statuses(tmp_path):
    intake = _intake(
        [
            _assumption("tmp_assumption_1", "CA-01", evidence_status="open_dependency"),
            _assumption("tmp_assumption_2", "CA-02", evidence_status="external_validation_required"),
            _assumption("tmp_assumption_3", "CA-03", evidence_status="undecidable"),
        ]
    )
    ops, result = _run_raw_intake(tmp_path, intake, SOURCE_WITHOUT)
    assert result.accepted
    by_id = {a["id"]: a["evidence_status"] for a in _assumptions(ops)}
    assert by_id["A-0001"] == "open_dependency"
    assert by_id["A-0002"] == "external_validation_required"
    assert by_id["A-0003"] == "undecidable"


def test_model_inferred_verified_claim_is_forced_down(tmp_path):
    intake = _intake(
        [_assumption("tmp_assumption_1", "CA-01", evidence_status="verified_user_stated")]
    )
    ops, result = _run_raw_intake(tmp_path, intake, SOURCE_WITHOUT)
    assert result.accepted
    first = _assumptions(ops)[0]
    assert first["source_type"] == "model_inferred"
    assert first["evidence_status"] == "model_inferred"


def test_v1_extraction_assumptions_have_no_evidence_status(tmp_path):
    ops = HarnessOperations(
        tmp_path / "sessions", "v1_ev", model=DeterministicMockModel(), now=lambda: TS
    )
    ops.create_session()
    ops.add_source(SOURCE_WITH_EXCERPT)
    result = ops.run_initial_extraction()
    assert result.accepted
    for assumption in ops.ledger()["assumptions"]:
        assert "evidence_status" not in assumption
        assert "premise_origin" not in assumption
