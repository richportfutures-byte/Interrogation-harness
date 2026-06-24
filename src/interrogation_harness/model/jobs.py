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
    # V2 jobs (V2 spec Sections 3 and 4). intake creates entities by temp handle, like
    # initial_extraction. blind_spot_audit reports findings only; the harness converts
    # accepted findings into ordinary event-backed records.
    ModelJob.INTAKE_UNSTRUCTURED_INPUT: ModelJobSpec(
        job=ModelJob.INTAKE_UNSTRUCTURED_INPUT,
        may_create=True,
        allowed_event_types=CREATION_EVENT_TYPES,
    ),
    ModelJob.BLIND_SPOT_AUDIT: ModelJobSpec(
        job=ModelJob.BLIND_SPOT_AUDIT,
        may_create=False,
        allowed_event_types=frozenset(),
        records_event_type=EventType.AUDIT_RUN,
    ),
}


def job_spec(job: ModelJob | str) -> ModelJobSpec:
    """Return the strict job contract."""
    return JOB_SPECS[ModelJob(job)]


def extraction_job(protocol_version: str) -> ModelJob:
    """The extraction job for a protocol: V1 initial_extraction or V2 intake."""
    if protocol_version == "2.0.0":
        return ModelJob.INTAKE_UNSTRUCTURED_INPUT
    return ModelJob.INITIAL_EXTRACTION


def audit_job(protocol_version: str) -> ModelJob:
    """The audit job for a protocol: V1 contradiction_audit or V2 blind_spot_audit."""
    if protocol_version == "2.0.0":
        return ModelJob.BLIND_SPOT_AUDIT
    return ModelJob.CONTRADICTION_AUDIT


def build_model_request(job: ModelJob | str, **payload: object) -> ModelRequest:
    """Build a request payload for one of the five Section 12 jobs."""
    resolved = ModelJob(job)
    if resolved in (ModelJob.INITIAL_EXTRACTION, ModelJob.INTAKE_UNSTRUCTURED_INPUT):
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
