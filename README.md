# Stateful Interrogation Harness (v1)

A local, file backed, event sourced harness that converts messy human input into an
auditable, implementation grade ground truth record through a disciplined one question
at a time interrogation loop. The append only event log is the sole authority; the
ledger is a pure projection rebuilt from it. See SPEC.md for the canonical specification.

## Status

This repository is built in stages. Stage 1 delivers the project scaffold and the
type/schema layer only (object model records, status enums, event envelope, and the
closed event-type set). Storage, projection, validation, engines, and the CLI arrive in
later stages.

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
