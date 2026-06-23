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
python -m venv .venv
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
python -m interrogation_harness resume-session sample_session
```

## Sample Session

The committed sample lives at `sessions/sample_session/` and contains:

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
