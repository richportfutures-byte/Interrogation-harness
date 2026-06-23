"""StateMachine: legal entity transition tables (Section 10).

Pure data plus pure checks. No IO, no clock, no model. Any transition outside the
allowed set is illegal and raises :class:`IllegalTransition`; the caller (the validator
in a later stage, or the projector as a defensive guard) records the rejection and does
not mutate.
"""

from __future__ import annotations


class IllegalTransition(Exception):
    """Raised when a proposed state transition is not in the allowed set."""

    def __init__(self, entity_type: str, frm: str, to: str, message: str | None = None):
        self.entity_type = entity_type
        self.frm = frm
        self.to = to
        super().__init__(
            message or f"illegal {entity_type} transition: {frm} -> {to}"
        )


# Section 10 transition tables. Each maps a current state to the set of legal targets.
# A state absent from a table (or a target absent from its set) is illegal.
_TABLES: dict[str, dict[str, frozenset[str]]] = {
    "assumption": {
        "candidate": frozenset({"provisional", "locked", "rejected", "deferred"}),
        "provisional": frozenset({"locked", "rejected", "revised", "deferred"}),
        "locked": frozenset({"revised", "deferred"}),
        "revised": frozenset({"provisional", "locked", "rejected", "deferred"}),
        "deferred": frozenset({"provisional", "locked", "rejected", "revised"}),
        "rejected": frozenset({"revised"}),
    },
    "work_item": {
        "open": frozenset({"active", "deferred", "blocked"}),
        "active": frozenset({"answered", "deferred", "blocked"}),
        "answered": frozenset({"resolved", "open"}),
        "deferred": frozenset({"open", "blocked"}),
        "blocked": frozenset({"open", "deferred"}),
        "resolved": frozenset({"open"}),
    },
    "risk": {
        "open": frozenset({"mitigated", "accepted", "deferred"}),
        "mitigated": frozenset({"open"}),
        "accepted": frozenset({"open"}),
        "deferred": frozenset({"open"}),
    },
    "contradiction": {
        "open": frozenset({"resolved", "deferred"}),
        "resolved": frozenset({"open"}),
        "deferred": frozenset({"open"}),
    },
    "term": {
        "undefined": frozenset({"provisional", "locked", "rejected"}),
        "provisional": frozenset({"locked", "revised", "rejected"}),
        "locked": frozenset({"revised"}),
        "revised": frozenset({"provisional", "locked", "rejected"}),
        "rejected": frozenset({"revised"}),
    },
    "decision": {
        "needed": frozenset({"provisional", "locked", "deferred", "rejected"}),
        "provisional": frozenset({"locked", "revised", "deferred"}),
        "locked": frozenset({"revised"}),
        "revised": frozenset({"provisional", "locked", "rejected"}),
        "deferred": frozenset({"provisional", "locked", "rejected"}),
        "rejected": frozenset({"revised"}),
    },
}

ENTITY_TYPES = frozenset(_TABLES)


class StateMachine:
    """Legal transition checks for every entity type in Section 10."""

    TABLES = _TABLES

    @classmethod
    def allowed_targets(cls, entity_type: str, frm: str) -> frozenset[str]:
        try:
            table = cls.TABLES[entity_type]
        except KeyError as exc:
            raise ValueError(f"unknown entity type: {entity_type!r}") from exc
        return table.get(frm, frozenset())

    @classmethod
    def is_allowed(cls, entity_type: str, frm: str, to: str) -> bool:
        return to in cls.allowed_targets(entity_type, frm)

    @classmethod
    def check(cls, entity_type: str, frm: str, to: str) -> None:
        """Raise :class:`IllegalTransition` if ``frm -> to`` is not allowed."""
        if not cls.is_allowed(entity_type, frm, to):
            raise IllegalTransition(entity_type, frm, to)
