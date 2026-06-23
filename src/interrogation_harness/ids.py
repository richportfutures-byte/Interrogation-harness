"""IdAllocator: durable identity minting at acceptance (Section 7.1).

The harness owns identity. Durable IDs are minted only here, only when a creating event
is accepted, monotonic per prefix per session. The model emits temporary handles only
(tmp_assumption_1, tmp_work_1, ...); any durable ID where only a temp handle is allowed
is rejected. The allocator derives the next value per prefix from existing durable IDs
(from the projection or from accepted events), never from model output.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

ID_PREFIXES = ("A", "T", "D", "R", "C", "W")

# Maps the noun in a temp handle to the durable ID prefix.
_HANDLE_NOUN_TO_PREFIX = {
    "assumption": "A",
    "term": "T",
    "decision": "D",
    "risk": "R",
    "contradiction": "C",
    "work": "W",
}

_TEMP_HANDLE_RE = re.compile(
    r"^tmp_(assumption|term|decision|risk|contradiction|work)_\w+$"
)
_DURABLE_ID_RE = re.compile(r"^[ATDRCW]-\d+$")
_LEDGER_ARRAYS = (
    "assumptions",
    "terms",
    "decisions",
    "risks",
    "contradictions",
    "work_items",
)


class IdAllocationError(Exception):
    """Base class for identity allocation failures."""


class DurableIdInCreationError(IdAllocationError):
    """A durable ID appeared where only a temp handle is allowed."""


class DuplicateTempHandleError(IdAllocationError):
    """The same temp handle appeared twice in one creation proposal."""


class UnknownTempHandleError(IdAllocationError):
    """A handle did not match the temp handle form."""


class IdAllocator:
    """Mints monotonic durable IDs per prefix for one session."""

    def __init__(self, existing_ids: Iterable[str] = ()) -> None:
        self._counters: dict[str, int] = {prefix: 0 for prefix in ID_PREFIXES}
        for value in existing_ids:
            match = _DURABLE_ID_RE.match(value) if isinstance(value, str) else None
            if not match:
                continue
            prefix = value[0]
            number = int(value[2:])
            if number > self._counters[prefix]:
                self._counters[prefix] = number

    # -- construction from authoritative state -----------------------------

    @classmethod
    def from_events(cls, events: Iterable[dict]) -> "IdAllocator":
        """Seed counters from durable IDs recorded in event ref_maps."""
        ids: list[str] = []
        for event in events:
            ref_map = event.get("ref_map")
            if isinstance(ref_map, dict):
                ids.extend(str(v) for v in ref_map.values())
        return cls(ids)

    @classmethod
    def from_ledger(cls, ledger: dict) -> "IdAllocator":
        """Seed counters from the durable IDs present in the projection."""
        ids: list[str] = []
        for key in _LEDGER_ARRAYS:
            for entity in ledger.get(key, []):
                ident = entity.get("id")
                if isinstance(ident, str):
                    ids.append(ident)
        return cls(ids)

    # -- inspection --------------------------------------------------------

    @staticmethod
    def is_durable_id(value: object) -> bool:
        return isinstance(value, str) and bool(_DURABLE_ID_RE.match(value))

    @staticmethod
    def is_temp_handle(value: object) -> bool:
        return isinstance(value, str) and bool(_TEMP_HANDLE_RE.match(value))

    def peek_next(self, prefix: str) -> str:
        """Return the next ID for a prefix without consuming it."""
        if prefix not in self._counters:
            raise ValueError(f"unknown prefix: {prefix!r}")
        return f"{prefix}-{self._counters[prefix] + 1:04d}"

    # -- minting -----------------------------------------------------------

    def allocate(self, temp_handles: Iterable[str]) -> dict[str, str]:
        """Mint a durable ID for each temp handle; return the handle to ID ref_map.

        Rejects durable IDs (only temp handles are allowed here), unknown handle forms,
        and duplicate handles. IDs are minted monotonically per prefix, so no minted ID
        can collide with an existing one or with another in the same batch.
        """
        ref_map: dict[str, str] = {}
        seen: set[str] = set()
        for handle in temp_handles:
            if self.is_durable_id(handle):
                raise DurableIdInCreationError(
                    f"durable ID not allowed in creation: {handle!r}"
                )
            match = _TEMP_HANDLE_RE.match(handle) if isinstance(handle, str) else None
            if match is None:
                raise UnknownTempHandleError(f"not a temp handle: {handle!r}")
            if handle in seen:
                raise DuplicateTempHandleError(f"duplicate temp handle: {handle!r}")
            seen.add(handle)
            prefix = _HANDLE_NOUN_TO_PREFIX[match.group(1)]
            self._counters[prefix] += 1
            ref_map[handle] = f"{prefix}-{self._counters[prefix]:04d}"
        return ref_map

    @staticmethod
    def assert_no_durable_ids(values: Iterable[object]) -> None:
        """Raise if any value is a durable ID (for scanning creation proposals)."""
        for value in values:
            if IdAllocator.is_durable_id(value):
                raise DurableIdInCreationError(
                    f"durable ID not allowed in creation field: {value!r}"
                )
