# Stateful Interrogation Harness (v1)

A local, file backed, event sourced harness that converts messy human input into an
auditable, implementation grade ground truth record through a disciplined one question
at a time interrogation loop. The append only event log is the sole authority; the
ledger is a pure projection rebuilt from it. See SPEC.md for the canonical specification.

## Status

This repository implements the local v1 harness described in SPEC.md: file-backed
sessions, append-only events, deterministic projection rebuilds, validation, offline
mock model jobs, engines, a CLI, the Section 20 acceptance suite, and a committed
sample session.

## Requirements

Python 3.10 or newer. No runtime dependencies (standard library only). The only
development dependency is pytest.

## Setup

Using uv (recommended):

```
uv venv
uv pip install -e ".[dev]"
```

Using the standard library tooling as a fallback:

```
uv venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Running the tests

The full suite runs fully offline against the deterministic mock model:

```
uv run pytest
```

(or simply `pytest` inside an activated virtual environment).

## CLI

The CLI is available as a Python module:

```
uv run python -m interrogation_harness --root sessions show-ledger sample_session
uv run python -m interrogation_harness --root sessions show-open-work sample_session
uv run python -m interrogation_harness --root sessions resume-session sample_session
```

The default root is `sessions`, so the shorter form works in an installed or activated
environment:

```
uv run python -m interrogation_harness resume-session sample_session
```

## Live Gemini Adapter

The deterministic mock remains the default model adapter so tests and acceptance
rebuilds run offline. To use Google Gemini for real interrogation runs, set:

```
export INTERROGATION_HARNESS_MODEL_PROVIDER=gemini
export GEMINI_API_KEY="your-key"
export GEMINI_MODEL="gemini-3.5-flash"
```

Optional knobs:

```
export GEMINI_API_VERSION="v1"
export GEMINI_TIMEOUT_SECONDS="120"
export GEMINI_MAX_OUTPUT_TOKENS="65536"
export GEMINI_THINKING_LEVEL="high"
export GEMINI_TEMPERATURE="0.2"
```

The adapter uses Gemini's Interactions API with `response_format` set to JSON schema.
The harness still treats the model as untrusted: raw output is recorded, then parsed,
schema-checked, semantically validated, and only accepted events mutate the ledger.

## Sample Sessions

The committed V1 sample lives at `sessions/sample_session/` and contains:

```
source.md
events.jsonl
ledger.json
final_artifact.md
```

Regenerate it deterministically from the real harness operations:

```
uv run python scripts/build_sample_session.py
```

The builder uses a fixed clock and drives the same event log, validator, projector,
audit, force-close, and artifact paths used by the CLI. It does not hand-write the
session files.

The sample demonstrates the Section 24 requirements: at least three candidate
assumptions, a model-inferred assumption, verified user-stated provenance, a high
blast-radius work item, an unknown answer routed to an open risk, a deferred item, a
revised assumption, a rejected illegal transition, and a force-closed final artifact
that keeps unresolved high-risk work visible.

The committed V2 sample lives at `sessions/v2_sample_session/` and is regenerated with:

```
uv run python scripts/build_v2_sample_session.py
```

It demonstrates V2 activation, unstructured intake, premise answer assimilation,
blind-spot audit conversion, closure gating, controlled incomplete force close, and
the final V2 artifact format.
