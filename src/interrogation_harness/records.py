"""Section 4 object model: entities and the single work item pool.

This module defines the typed shapes only (dataclasses, enums, closed value sets). It
implements no behavior: no serialization, no validation, no state transitions, no
identity minting. Those live in their own modules in later stages.

Field order within a dataclass is not significant: canonical serialization (Section 9)
sorts object keys lexicographically, so the declaration order here is chosen only to
satisfy dataclass default-ordering rules (required fields first, defaulted fields last).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Closed value sets (enums)
# ---------------------------------------------------------------------------


class AssumptionStatus(str, Enum):
    """Assumption.status, Section 4.1."""

    CANDIDATE = "candidate"
    PROVISIONAL = "provisional"
    LOCKED = "locked"
    REJECTED = "rejected"
    REVISED = "revised"
    DEFERRED = "deferred"


class SourceType(str, Enum):
    """Assumption.source_type, Section 4.1 and Section 11."""

    USER_STATED = "user_stated"
    MODEL_INFERRED = "model_inferred"
    EXTERNAL_REQUIRED = "external_required"


class BlastRadius(str, Enum):
    """Blast radius classification, Section 5. Used by Assumption and WorkItem."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Severity(str, Enum):
    """Severity classification. Used by Risk.severity and Contradiction.severity.

    Mirrors the blast radius rubric value set (Section 5), kept as a distinct enum
    because the spec names these fields severity rather than blast_radius.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TermStatus(str, Enum):
    """Term.status, Section 4.1."""

    UNDEFINED = "undefined"
    PROVISIONAL = "provisional"
    LOCKED = "locked"
    REJECTED = "rejected"
    REVISED = "revised"


class DecisionStatus(str, Enum):
    """Decision.status, Section 4.1."""

    NEEDED = "needed"
    PROVISIONAL = "provisional"
    LOCKED = "locked"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    REVISED = "revised"


class RiskStatus(str, Enum):
    """Risk.status, Section 4.1."""

    OPEN = "open"
    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    DEFERRED = "deferred"


class ContradictionStatus(str, Enum):
    """Contradiction.status, Section 4.1."""

    OPEN = "open"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class WorkItemKind(str, Enum):
    """WorkItem.kind, Section 4.2."""

    RESOLVE_ASSUMPTION = "resolve_assumption"
    DEFINE_TERM = "define_term"
    MAKE_DECISION = "make_decision"
    RESOLVE_CONTRADICTION = "resolve_contradiction"
    MITIGATE_RISK = "mitigate_risk"
    VALIDATE_EXTERNAL = "validate_external"
    CLARIFY = "clarify"


class WorkItemStatus(str, Enum):
    """WorkItem.status, Section 4.2 and Section 10."""

    OPEN = "open"
    ACTIVE = "active"
    ANSWERED = "answered"
    DEFERRED = "deferred"
    RESOLVED = "resolved"
    BLOCKED = "blocked"


class AnswerClass(str, Enum):
    """Supported answer classes that may appear in WorkItem.answer_options, Section 13.

    Freeform clarification is handled at answer time and is not a discrete token here.
    """

    CONFIRM = "confirm"
    REJECT = "reject"
    REVISE = "revise"
    DEFER = "defer"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# V2 optional value sets (V2 Implementation Spec, Section 2.3)
# ---------------------------------------------------------------------------


class PremiseOrigin(str, Enum):
    """Assumption.premise_origin (V2). How a premise entered the record."""

    INTAKE = "intake"
    ANSWER = "answer"
    BLIND_SPOT = "blind_spot"
    AUDIT = "audit"
    MANUAL = "manual"


class EvidenceStatus(str, Enum):
    """Assumption.evidence_status (V2). The standard-of-evidence tag (protocol Section 2.4)."""

    VERIFIED_USER_STATED = "verified_user_stated"
    MODEL_INFERRED = "model_inferred"
    UNVERIFIED_ACCEPTED = "unverified_accepted"
    OPEN_DEPENDENCY = "open_dependency"
    EXTERNAL_VALIDATION_REQUIRED = "external_validation_required"
    UNDECIDABLE = "undecidable"


class GapType(str, Enum):
    """WorkItem.gap_type (V2). The gap taxonomy that produced a derived question."""

    UNSTATED_PRECONDITION = "unstated_precondition"
    SCOPE_BOUNDARY = "scope_boundary"
    AUTHORITY_OWNERSHIP = "authority_ownership"
    FAILURE_MODE = "failure_mode"
    METRIC_DEFINITION = "metric_definition"
    TEMPORAL_ASSUMPTION = "temporal_assumption"
    DEPENDENCY_CHAIN = "dependency_chain"
    INPUT_COMPLETENESS = "input_completeness"
    CONTRADICTION = "contradiction"
    SCOPE_CONFLICT = "scope_conflict"
    BLIND_SPOT = "blind_spot"


# ---------------------------------------------------------------------------
# Shared sub-records
# ---------------------------------------------------------------------------


@dataclass
class RevisionEntry:
    """A single entry in an entity revision_history.

    The spec gives the concrete shape for assumptions (Section 4.1):
    event_id, prior_statement, new_statement. The same shape is reused for Term and
    Decision revision history, where prior_statement and new_statement hold the prior
    and new primary text (the definition for a term, the decision text for a decision).
    """

    event_id: str
    prior_statement: str
    new_statement: str


# ---------------------------------------------------------------------------
# Entities (Section 4.1)
# ---------------------------------------------------------------------------


@dataclass
class Assumption:
    """Assumption entity (A-NNNN), Section 4.1."""

    id: str
    statement: str
    status: AssumptionStatus
    source_type: SourceType
    blast_radius: BlastRadius
    downstream_impact: str
    risk_if_wrong: str
    created_event: str
    updated_event: str
    source_excerpt: str | None = None
    source_excerpt_verified: bool = False
    tested_by_work_item: str | None = None
    user_answer_events: list[str] = field(default_factory=list)
    revision_history: list[RevisionEntry] = field(default_factory=list)
    # V2 optional fields (omitted from the ledger when null/empty, Section 2.4).
    intake_label: str | None = None
    premise_origin: PremiseOrigin | None = None
    evidence_status: EvidenceStatus | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class Term:
    """Term entity (T-NNNN), Section 4.1."""

    id: str
    term: str
    status: TermStatus
    created_event: str
    updated_event: str
    definition: str | None = None
    revision_history: list[RevisionEntry] = field(default_factory=list)


@dataclass
class Decision:
    """Decision entity (D-NNNN), Section 4.1."""

    id: str
    decision: str
    status: DecisionStatus
    created_event: str
    updated_event: str
    rationale: str | None = None
    revision_history: list[RevisionEntry] = field(default_factory=list)


@dataclass
class Risk:
    """Risk entity (R-NNNN), Section 4.1."""

    id: str
    statement: str
    severity: Severity
    status: RiskStatus
    created_event: str
    updated_event: str
    source_refs: list[str] = field(default_factory=list)


@dataclass
class Contradiction:
    """Contradiction entity (C-NNNN), Section 4.1."""

    id: str
    refs: list[str]
    severity: Severity
    description: str
    status: ContradictionStatus
    created_event: str
    updated_event: str
    resolution_work_item: str | None = None


# ---------------------------------------------------------------------------
# Work item (Section 4.2)
# ---------------------------------------------------------------------------


@dataclass
class WorkItem:
    """Work item (W-NNNN): a single pool of all open interrogation work, Section 4.2."""

    id: str
    kind: WorkItemKind
    status: WorkItemStatus
    question: str
    why_it_matters: str
    what_breaks_if_wrong: str
    blast_radius: BlastRadius
    blocks_closure: bool
    created_event: str
    updated_event: str
    target_entity: str | None = None
    recommended_default: str | None = None
    recommended_default_basis: str | None = None
    answer_options: list[AnswerClass] = field(default_factory=list)
    deferred_reason: str | None = None
    # V2 optional fields (omitted from the ledger when null/empty, Section 2.4).
    derived_question_label: str | None = None
    gap_type: GapType | None = None
    source_assumption_ids: list[str] = field(default_factory=list)
    blocking_reason: str | None = None
