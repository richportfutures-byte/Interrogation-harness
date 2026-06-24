"""Model adapter boundary, deterministic mock, and optional live adapters."""

from interrogation_harness.model.adapter import ModelAdapter, ModelJob, ModelRequest
from interrogation_harness.model.config import default_model_adapter_from_env
from interrogation_harness.model.gemini import GeminiAdapterError, GeminiModelAdapter
from interrogation_harness.model.mock import (
    DeterministicMockModel,
    MockScenario,
)

DEFAULT_MODEL_ADAPTER = default_model_adapter_from_env()

__all__ = [
    "DEFAULT_MODEL_ADAPTER",
    "DeterministicMockModel",
    "GeminiAdapterError",
    "GeminiModelAdapter",
    "MockScenario",
    "ModelAdapter",
    "ModelJob",
    "ModelRequest",
    "default_model_adapter_from_env",
]
