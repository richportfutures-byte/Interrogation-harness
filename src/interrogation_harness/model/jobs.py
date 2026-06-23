"""Model job definitions and strict permission sets, Section 12."""

from __future__ import annotations

from dataclasses import dataclass

from interrogation_harness.events import EventType
from interrogation_harness.model.adapter import ModelJob, ModelRequest

CREATION_EVENT_TYPES = frozenset(
    {
        EventType.ASSUMPTION_CREATED.value,
        EventType.TERM_CREATED.value,
        EventType.DECISION_CREATED.value,
        EventType.RISK_CREATED.value,
        EventType.CONTRADICTION_CREATED.value,
        EventType.WORK_ITEM_CREATED.value,
    }
)

TRANSITION_EVENT_TYPES = frozenset(
    {
        EventType.ASSUMPTION_TRANSITIONED.value,
        EventType.TERM_TRANSITIONED.value,
        EventType.DECISION_TRANSITIONED.value,
        EventType.RISK_TRANSITIONED.value,
        EventType.CONTRADICTION_TRANSITIONED.value,
        EventType.WORK_ITEM_STATUS_CHANGED.value,
    }
)

INTERPRET_ALLOWED_EVENT_TYPES = CREATION_EVENT_TYPES | TRANSITION_EVENT_TYPES


@dataclass(frozen=True)
class ModelJobSpec:
    """Static contract for one model job."""

    job: ModelJob
    may_create: bool
    allowed_event_types: frozenset[str]
    records_event_type: EventType | None = None


JOB_SPECS: dict[ModelJob, ModelJobSpec] = {
    ModelJob.INITIAL_EXTRACTION: ModelJobSpec(
        job=ModelJob.INITIAL_EXTRACTION,
        may_create=True,
        allowed_event_types=CREATION_EVENT_TYPES,
    ),
    ModelJob.RANK_NEXT_WORK_ITEM: ModelJobSpec(
        job=ModelJob.RANK_NEXT_WORK_ITEM,
        may_create=False,
        allowed_event_types=frozenset(),
    ),
    ModelJob.INTERPRET_USER_ANSWER: ModelJobSpec(
        job=ModelJob.INTERPRET_USER_ANSWER,
        may_create=True,
        allowed_event_types=INTERPRET_ALLOWED_EVENT_TYPES,
    ),
    ModelJob.CONTRADICTION_AUDIT: ModelJobSpec(
        job=ModelJob.CONTRADICTION_AUDIT,
        may_create=False,
        allowed_event_types=frozenset(),
        records_event_type=EventType.AUDIT_RUN,
    ),
    ModelJob.ARTIFACT_GENERATION: ModelJobSpec(
        job=ModelJob.ARTIFACT_GENERATION,
        may_create=False,
        allowed_event_types=frozenset(),
        records_event_type=EventType.ARTIFACT_GENERATED,
    ),
}


def job_spec(job: ModelJob | str) -> ModelJobSpec:
    """Return the strict job contract."""
    return JOB_SPECS[ModelJob(job)]


def build_model_request(job: ModelJob | str, **payload: object) -> ModelRequest:
    """Build a request payload for one of the five Section 12 jobs."""
    resolved = ModelJob(job)
    if resolved == ModelJob.INITIAL_EXTRACTION:
        payload.setdefault("do_not_mint_durable_ids", True)
        payload.setdefault("mark_model_inferences", True)
        payload.setdefault("cite_source_excerpts", True)
    if resolved == ModelJob.RANK_NEXT_WORK_ITEM:
        payload.setdefault(
            "policy",
            [
                "prefer_high_blast_radius",
                "prefer_closure_blockers",
                "one_question_at_a_time",
            ],
        )
    if resolved == ModelJob.ARTIFACT_GENERATION:
        payload.setdefault("closure_mode", "force_close")
    return ModelRequest.from_payload(resolved, payload)
