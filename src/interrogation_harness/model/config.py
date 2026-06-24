"""Runtime model adapter selection."""

from __future__ import annotations

import os
from collections.abc import Mapping

from interrogation_harness.model.adapter import ModelAdapter
from interrogation_harness.model.gemini import GeminiModelAdapter
from interrogation_harness.model.mock import DeterministicMockModel


def default_model_adapter_from_env(
    environ: Mapping[str, str] | None = None,
) -> ModelAdapter:
    """Return the configured default adapter.

    The offline deterministic mock remains the default so tests and local acceptance
    runs never require network access. Set INTERROGATION_HARNESS_MODEL_PROVIDER=gemini
    to use the live Gemini adapter.
    """
    env = os.environ if environ is None else environ
    provider = env.get("INTERROGATION_HARNESS_MODEL_PROVIDER", "mock").strip().lower()
    if provider in {"", "mock", "deterministic", "deterministic-mock"}:
        return DeterministicMockModel()
    if provider in {"gemini", "google", "google-gemini"}:
        return GeminiModelAdapter.from_env(env)
    raise ValueError(f"unknown model provider: {provider!r}")
