"""Stage 4 proof: model adapter boundary and deterministic mock."""

from __future__ import annotations

import copy
import json

import pytest

from interrogation_harness.model import (
    DEFAULT_MODEL_ADAPTER,
    DeterministicMockModel,
    MockScenario,
    ModelAdapter,
    ModelJob,
    ModelRequest,
)


def _request(job: ModelJob, payload=None) -> ModelRequest:
    return ModelRequest.from_payload(job, payload or {"session_id": "sess_demo"})


@pytest.mark.parametrize(
    ("job", "scenario"),
    [
        (ModelJob.INITIAL_EXTRACTION, MockScenario.INITIAL_EXTRACTION),
        (ModelJob.RANK_NEXT_WORK_ITEM, MockScenario.RANK_NEXT_WORK_ITEM),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.INTERPRET_CONFIRM),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.INTERPRET_REJECT),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.INTERPRET_REVISE),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.INTERPRET_DEFER),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.INTERPRET_UNKNOWN),
        (ModelJob.CONTRADICTION_AUDIT, MockScenario.CONTRADICTION_AUDIT),
        (ModelJob.ARTIFACT_GENERATION, MockScenario.ARTIFACT_GENERATION),
        (ModelJob.ARTIFACT_GENERATION, MockScenario.ARTIFACT_GENERATION_V2),
        (ModelJob.ARTIFACT_GENERATION, MockScenario.ARTIFACT_FORCE_CLOSED_INCOMPLETE),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.MALFORMED_JSON),
        (ModelJob.INTERPRET_USER_ANSWER, MockScenario.ILLEGAL_TRANSITION),
        (ModelJob.INITIAL_EXTRACTION, MockScenario.CREATION_WITH_DURABLE_ID),
    ],
)
def test_mock_returns_raw_output_for_required_scenarios(job, scenario):
    output = DeterministicMockModel().complete(_request(job), scenario=scenario.value)
    assert isinstance(output, str)
    assert output


def test_mock_is_deterministic_for_same_input_and_scenario():
    model = DeterministicMockModel()
    request = _request(
        ModelJob.INTERPRET_USER_ANSWER,
        {
            "session_id": "sess_demo",
            "answer_class": "revise",
            "nested": {"items": ["a", "b"]},
        },
    )

    first = model.complete(request, scenario=MockScenario.INTERPRET_REVISE.value)
    second = model.complete(request, scenario=MockScenario.INTERPRET_REVISE.value)
    assert first == second


def test_adapter_boundary_does_not_mutate_passed_input_objects():
    payload = {
        "session_id": "sess_demo",
        "answer_class": "unknown",
        "projection": {"work_items": [{"id": "W-0001", "status": "active"}]},
    }
    before = copy.deepcopy(payload)
    request = ModelRequest.from_payload(ModelJob.INTERPRET_USER_ANSWER, payload)

    output = DeterministicMockModel().complete(request)

    assert isinstance(output, str)
    assert payload == before
    with pytest.raises(TypeError):
        request.payload["session_id"] = "changed"
    with pytest.raises(TypeError):
        request.payload["projection"]["work_items"][0]["status"] = "changed"


def test_mock_requires_no_live_api_or_network_call(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("network should not be used")

    monkeypatch.setattr("socket.create_connection", fail_network)
    output = DeterministicMockModel().complete(_request(ModelJob.ARTIFACT_GENERATION))
    assert isinstance(output, str)
    assert json.loads(output)["artifact_markdown"].startswith("# Final Artifact")


def test_stage5_negative_scenarios_are_available():
    model = DeterministicMockModel()

    malformed = model.complete(
        _request(ModelJob.INTERPRET_USER_ANSWER),
        scenario=MockScenario.MALFORMED_JSON.value,
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed)

    illegal = json.loads(
        model.complete(
            _request(ModelJob.INTERPRET_USER_ANSWER),
            scenario=MockScenario.ILLEGAL_TRANSITION.value,
        )
    )
    transition = illegal["proposed_events"][0]["payload"]
    assert transition["from"] == "rejected"
    assert transition["to"] == "locked"

    durable_id_creation = json.loads(
        model.complete(
            _request(ModelJob.INITIAL_EXTRACTION),
            scenario=MockScenario.CREATION_WITH_DURABLE_ID.value,
        )
    )
    assert durable_id_creation["assumptions"][0]["id"] == "A-0001"


def test_mock_is_default_model_for_tests():
    assert isinstance(DEFAULT_MODEL_ADAPTER, ModelAdapter)
    assert isinstance(DEFAULT_MODEL_ADAPTER, DeterministicMockModel)
