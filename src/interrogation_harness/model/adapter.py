"""Swappable model adapter boundary.

The harness treats model calls as isolated string-producing operations. The adapter
returns raw model output only. Parsing, validation, retry handling, event recording,
and state mutation belong to later pipeline layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable


class ModelJob(str, Enum):
    """Closed model job set: V1 jobs (Section 12) plus V2 jobs (V2 spec Section 3)."""

    INITIAL_EXTRACTION = "initial_extraction"
    RANK_NEXT_WORK_ITEM = "rank_next_work_item"
    INTERPRET_USER_ANSWER = "interpret_user_answer"
    CONTRADICTION_AUDIT = "contradiction_audit"
    ARTIFACT_GENERATION = "artifact_generation"
    # V2 jobs.
    INTAKE_UNSTRUCTURED_INPUT = "intake_unstructured_input"
    BLIND_SPOT_AUDIT = "blind_spot_audit"


# V1 and V2 job groupings, used by protocol-aware routing helpers (V2 spec Section 3).
V1_JOBS = frozenset(
    {
        ModelJob.INITIAL_EXTRACTION,
        ModelJob.CONTRADICTION_AUDIT,
    }
)
V2_JOBS = frozenset(
    {
        ModelJob.INTAKE_UNSTRUCTURED_INPUT,
        ModelJob.BLIND_SPOT_AUDIT,
    }
)
SHARED_JOBS = frozenset(
    {
        ModelJob.RANK_NEXT_WORK_ITEM,
        ModelJob.INTERPRET_USER_ANSWER,
        ModelJob.ARTIFACT_GENERATION,
    }
)


def _freeze(value: Any) -> Any:
    """Recursively copy containers into immutable equivalents for adapter inputs."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ModelRequest:
    """A model request with an immutable payload snapshot.

    ``from_payload`` takes a defensive immutable copy, so callers can pass ordinary
    dictionaries without giving an adapter permission to mutate their objects.
    """

    job: ModelJob
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_payload(cls, job: ModelJob | str, payload: Mapping[str, Any]) -> "ModelRequest":
        return cls(job=ModelJob(job), payload=_freeze(payload))


@runtime_checkable
class ModelAdapter(Protocol):
    """Protocol implemented by live adapters and deterministic mocks."""

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        """Return the raw model output string for ``request``."""
