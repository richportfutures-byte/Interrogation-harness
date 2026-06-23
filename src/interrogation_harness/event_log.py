"""EventLog: append-only event writing and idempotency reconstruction (Sections 6, 7).

Responsibilities for this stage:
  - Append events, minting a sequential ``event_id`` (E-0001, E-0002, ...) at append
    time. IDs are never reused.
  - Preserve every event, including failure and rejection records.
  - Reconstruct the idempotency map from ``events.jsonl`` alone (no side file), counting
    a key as accepted only when its operation produced an accepted result.

This module does not mint durable entity IDs, validate, or build the ledger. The clock
is injected: the caller supplies ``timestamp`` so this writer never reads a clock.
"""

from __future__ import annotations

import re

from . import canonical
from .events import SCHEMA_VERSION, Actor, Event, EventType
from .session_store import SessionStore

_EVENT_ID_RE = re.compile(r"^E-(\d+)$")

# Section 7 idempotency: these event types are explicitly NOT accepted results.
_FAILURE_OR_REJECTION = frozenset(
    {EventType.OPERATION_FAILED.value, EventType.PROPOSAL_REJECTED.value}
)


class EventLog:
    """Append-only access to a session's event log."""

    def __init__(self, store: SessionStore) -> None:
        self.store = store

    # -- reading -----------------------------------------------------------

    def read_events(self) -> list[dict]:
        """Return all events as parsed dicts, in append order."""
        return [canonical.loads(line) for line in self.store.read_event_lines()]

    def next_event_id(self) -> str:
        """Mint the next sequential event_id from the current log contents."""
        highest = 0
        for event in self.read_events():
            match = _EVENT_ID_RE.match(str(event.get("event_id", "")))
            if match:
                highest = max(highest, int(match.group(1)))
        return f"E-{highest + 1:04d}"

    # -- appending ---------------------------------------------------------

    def append(
        self,
        *,
        event_type: EventType,
        actor: Actor,
        session_id: str,
        correlation_id: str,
        idempotency_key: str,
        timestamp: str,
        payload: dict | None = None,
        ref_map: dict[str, str] | None = None,
    ) -> dict:
        """Append one event, minting its ``event_id``. Returns the serialized dict."""
        event = Event(
            event_id=self.next_event_id(),
            session_id=session_id,
            timestamp=timestamp,
            event_type=event_type,
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            schema_version=SCHEMA_VERSION,
            payload=dict(payload or {}),
            ref_map=ref_map,
        )
        record = self._to_dict(event)
        self.store.append_event_line(canonical.dumps_event_line(record))
        return record

    # -- idempotency -------------------------------------------------------

    def idempotency_map(self) -> dict[str, str]:
        """Map each accepted operation's idempotency_key to its correlation_id.

        Events are grouped by correlation_id. A correlation is accepted only if it
        carries at least one accepted, non-failure, non-rejection result event (see
        :meth:`_is_accepted_result`). Failure and rejection only correlations are
        preserved in the log but do not populate the map, so their key stays reusable.
        """
        by_correlation: dict[str, dict] = {}
        for event in self.read_events():
            correlation = event.get("correlation_id")
            info = by_correlation.setdefault(
                correlation, {"key": event.get("idempotency_key"), "accepted": False}
            )
            if self._is_accepted_result(event):
                info["accepted"] = True

        accepted: dict[str, str] = {}
        for correlation, info in by_correlation.items():
            if info["accepted"] and info["key"] is not None:
                accepted[info["key"]] = correlation
        return accepted

    def accepted_correlation(self, idempotency_key: str) -> str | None:
        """Return the correlation_id of the accepted operation for this key, if any."""
        return self.idempotency_map().get(idempotency_key)

    @staticmethod
    def _is_accepted_result(event: dict) -> bool:
        """Whether an event represents an accepted operation result.

        Not accepted: OPERATION_FAILED, PROPOSAL_REJECTED, and MODEL_RESPONSE_RECORDED
        with ``payload.accepted == False``. Every other event type counts (it is only
        ever appended when its operation produced an accepted result).
        """
        event_type = event.get("event_type")
        if event_type in _FAILURE_OR_REJECTION:
            return False
        if (
            event_type == EventType.MODEL_RESPONSE_RECORDED.value
            and event.get("payload", {}).get("accepted") is False
        ):
            return False
        return True

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _to_dict(event: Event) -> dict:
        """Serialize an Event envelope to a plain dict.

        ``ref_map`` is included only when present (Section 6.1: it appears only on
        creating events). Key order is irrelevant; canonical serialization sorts keys.
        """
        record: dict = {
            "event_id": event.event_id,
            "session_id": event.session_id,
            "schema_version": event.schema_version,
            "timestamp": event.timestamp,
            "event_type": event.event_type.value,
            "actor": event.actor.value,
            "correlation_id": event.correlation_id,
            "idempotency_key": event.idempotency_key,
            "payload": event.payload,
        }
        if event.ref_map is not None:
            record["ref_map"] = event.ref_map
        return record
