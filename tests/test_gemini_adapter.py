"""Gemini adapter tests with a fake transport, no live API calls."""

from __future__ import annotations

import json

import pytest

from interrogation_harness.model import (
    GeminiAdapterError,
    GeminiModelAdapter,
    ModelJob,
    ModelRequest,
    default_model_adapter_from_env,
)
from interrogation_harness.model.gemini import schema_for_job
from interrogation_harness.model.mock import DeterministicMockModel


def test_default_provider_remains_offline_mock():
    adapter = default_model_adapter_from_env({})
    assert isinstance(adapter, DeterministicMockModel)


def test_gemini_provider_uses_env_config():
    adapter = default_model_adapter_from_env(
        {
            "INTERROGATION_HARNESS_MODEL_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "gemini-3.5-flash",
            "GEMINI_THINKING_LEVEL": "medium",
            "GEMINI_MAX_OUTPUT_TOKENS": "1234",
        }
    )
    assert isinstance(adapter, GeminiModelAdapter)
    assert adapter.model == "gemini-3.5-flash"
    assert adapter.thinking_level == "medium"
    assert adapter.max_output_tokens == 1234


def test_gemini_provider_requires_api_key():
    with pytest.raises(GeminiAdapterError, match="GEMINI_API_KEY"):
        default_model_adapter_from_env({"INTERROGATION_HARNESS_MODEL_PROVIDER": "gemini"})


def test_gemini_adapter_posts_interaction_and_returns_model_text():
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["body"] = body
        captured["timeout"] = timeout
        return {
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": '{"findings":[]}'}],
                }
            ],
        }

    adapter = GeminiModelAdapter(api_key="secret", transport=fake_transport)
    request = ModelRequest.from_payload(
        ModelJob.BLIND_SPOT_AUDIT,
        {"session_id": "s1", "projection": {"protocol_version": "2.0.0"}},
    )

    output = adapter.complete(request)

    assert output == '{"findings":[]}'
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1/interactions"
    assert captured["headers"]["x-goog-api-key"] == "secret"
    assert captured["timeout"] == 120.0
    body = captured["body"]
    assert body["model"] == "gemini-3.5-flash"
    assert body["store"] is False
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["response_format"]["schema"]["type"] == "object"
    assert body["generation_config"]["thinking_level"] == "high"
    assert "Job: blind_spot_audit" in body["input"]
    assert "secret" not in json.dumps(body)


def test_gemini_adapter_rejects_mock_scenarios():
    adapter = GeminiModelAdapter(api_key="secret", transport=lambda *_: {})
    request = ModelRequest.from_payload(ModelJob.RANK_NEXT_WORK_ITEM, {})
    with pytest.raises(GeminiAdapterError, match="mock scenarios"):
        adapter.complete(request, scenario="rank_next_work_item")


def test_gemini_adapter_errors_without_text_output():
    adapter = GeminiModelAdapter(
        api_key="secret",
        transport=lambda *_: {"status": "completed", "steps": []},
    )
    request = ModelRequest.from_payload(ModelJob.RANK_NEXT_WORK_ITEM, {})
    with pytest.raises(GeminiAdapterError, match="model output text"):
        adapter.complete(request)


@pytest.mark.parametrize(
    "job",
    [
        ModelJob.INITIAL_EXTRACTION,
        ModelJob.INTAKE_UNSTRUCTURED_INPUT,
        ModelJob.RANK_NEXT_WORK_ITEM,
        ModelJob.INTERPRET_USER_ANSWER,
        ModelJob.CONTRADICTION_AUDIT,
        ModelJob.BLIND_SPOT_AUDIT,
        ModelJob.ARTIFACT_GENERATION,
    ],
)
def test_each_job_has_structured_output_schema(job):
    schema = schema_for_job(job)
    assert schema["type"] == "object"
    assert schema["required"]
