"""Section 6 event model: the event envelope and the closed event-type set.

This module defines the typed shape of an event and the legal set of event types only.
It implements no behavior: no appending, no event_id minting, no idempotency handling,
no canonical serialization. Those live in their own modules in later stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Section 6.1: the schema version carried on every event envelope.
SCHEMA_VERSION = "1.0.0"


class Actor(str, Enum):
    """Event.actor, Section 6.1."""

    USER = "user"
    MODEL = "model"
    HARNESS = "harness"


class EventType(str, Enum):
    """The closed event-type set, Section 6.2. No event type outside this set is legal."""

    SESSION_CREATED = "SESSION_CREATED"
    SOURCE_ADDED = "SOURCE_ADDED"
    MODEL_RESPONSE_RECORDED = "MODEL_RESPONSE_RECORDED"
    OPERATION_FAILED = "OPERATION_FAILED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    ASSUMPTION_CREATED = "ASSUMPTION_CREATED"
    TERM_CREATED = "TERM_CREATED"
    DECISION_CREATED = "DECISION_CREATED"
    RISK_CREATED = "RISK_CREATED"
    CONTRADICTION_CREATED = "CONTRADICTION_CREATED"
    WORK_ITEM_CREATED = "WORK_ITEM_CREATED"
    QUESTION_ASKED = "QUESTION_ASKED"
    WORK_ITEM_STATUS_CHANGED = "WORK_ITEM_STATUS_CHANGED"
    ASSUMPTION_TRANSITIONED = "ASSUMPTION_TRANSITIONED"
    TERM_TRANSITIONED = "TERM_TRANSITIONED"
    DECISION_TRANSITIONED = "DECISION_TRANSITIONED"
    RISK_TRANSITIONED = "RISK_TRANSITIONED"
    CONTRADICTION_TRANSITIONED = "CONTRADICTION_TRANSITIONED"
    AUDIT_RUN = "AUDIT_RUN"
    FORCE_CLOSED = "FORCE_CLOSED"
    ARTIFACT_GENERATED = "ARTIFACT_GENERATED"


@dataclass
class Event:
    """The event envelope, Section 6.1.

    ref_map is present only on creating events and records the temporary handle to
    durable ID mapping decided at acceptance (Section 7.1); it is None otherwise.
    payload carries the per event-type body and is left untyped at this layer.
    """

    event_id: str
    session_id: str
    timestamp: str
    event_type: EventType
    actor: Actor
    correlation_id: str
    idempotency_key: str
    schema_version: str = SCHEMA_VERSION
    payload: dict[str, Any] = field(default_factory=dict)
    ref_map: dict[str, str] | None = None
