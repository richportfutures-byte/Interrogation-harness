"""Projection-only final artifact generation."""

from __future__ import annotations

from typing import Any

from interrogation_harness import canonical
from interrogation_harness.interrogation import OperationError
from interrogation_harness.model.adapter import ModelAdapter, ModelJob, ModelRequest
from interrogation_harness.validation import ModelContractValidator


class _StaticArtifactAdapter(ModelAdapter):
    """Adapter that returns a prebuilt raw artifact_generation response."""

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        return canonical.dumps_event_line(self.output)


class ArtifactGenerator:
    """Generate final_artifact.md from the current projection only."""

    def __init__(self, operations) -> None:
        self.ops = operations

    def generate_artifact(self) -> dict[str, Any]:
        ledger = self.ops.ledger()
        _assert_artifact_eligible(ledger)

        output = _artifact_output(ledger)
        ids = self.ops.op_ids("generate-artifact", {"projection": ledger})
        result = ModelContractValidator(
            self.ops.event_log,
            _StaticArtifactAdapter(output),
            self.ops.projector,
        ).run(
            ModelJob.ARTIFACT_GENERATION,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload={
                "projection": ledger,
                "closure_mode": "force_close" if ledger.get("force_closed") else "normal",
            },
        )
        if not result.accepted or result.parsed_output is None:
            raise ValueError("; ".join(result.errors) or "artifact_generation rejected")
        self.ops.store.write_artifact(result.parsed_output["artifact_markdown"])
        return {"accepted": True, "artifact_path": self.ops.store.artifact_path, "ledger": self.ops.ledger()}


def _artifact_output(ledger: dict[str, Any]) -> dict[str, Any]:
    markdown = _artifact_markdown(ledger)
    output = {
        "artifact_markdown": markdown,
        "blocking_warnings": _blocking_warning_lines(ledger),
        "open_risk_register": _open_risk_register(ledger),
        "traceability_summary": _traceability_summary(ledger),
    }
    if ledger.get("protocol_version") == "2.0.0":
        output["closure_status"] = _closure_status(ledger)
    return output


def _artifact_markdown(ledger: dict[str, Any]) -> str:
    if ledger.get("protocol_version") == "2.0.0":
        return _v2_artifact_markdown(ledger)
    sections = [
        ("Source Summary", [_source_summary(ledger)]),
        ("Locked Assumptions", _assumption_lines(ledger, "locked")),
        ("Provisional Assumptions", _assumption_lines(ledger, "provisional")),
        ("Rejected Assumptions", _assumption_lines(ledger, "rejected")),
        ("Revised Assumptions", _assumption_lines(ledger, "revised")),
        ("Locked Decisions", _decision_lines(ledger, "locked")),
        ("Defined Terms", _term_lines(ledger)),
        ("Open Work Items", _work_lines(ledger)),
        ("Open Risk Register", _risk_register_lines(ledger)),
        ("Contradictions and Resolutions", _contradiction_lines(ledger)),
        ("External Validation Required", _external_lines(ledger)),
        ("Implementation Constraints", ["Use the event log as the source of truth."]),
        ("Downstream Builder Instructions", ["Treat provisional and model-inferred assumptions as unconfirmed."]),
        ("Provenance Index", _provenance_lines(ledger)),
        ("Closure Mode", [_closure_line(ledger)]),
        ("Known Limits", _known_limits(ledger)),
    ]
    lines = ["# Final Artifact", ""]
    for title, body in sections:
        lines.append(f"## {title}")
        lines.append("")
        if body:
            lines.extend(f"- {item}" for item in body)
        else:
            lines.append("None")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _v2_artifact_markdown(ledger: dict[str, Any]) -> str:
    sections = [
        ("Scope and Objective", _v2_scope_lines(ledger)),
        ("Closure Status", _v2_closure_lines(ledger)),
        ("Locked Assumptions", _v2_assumption_register_lines(ledger, "locked")),
        ("Provisional and Unconfirmed Assumptions", _v2_unconfirmed_assumption_lines(ledger)),
        ("Revision Log", _v2_revision_lines(ledger)),
        ("Open Risks and Undecidable Assumptions", _v2_open_risk_lines(ledger)),
        ("Authority Map", _v2_authority_lines(ledger)),
        ("Failure-Mode Declarations", _v2_failure_mode_lines(ledger)),
        ("Definitions for Critical Terms", _term_lines(ledger)),
        ("Decisions", _v2_decision_lines(ledger)),
        ("Items Explicitly Excluded From Scope", _v2_exclusion_lines(ledger)),
        ("Validation Actions Still Required", _v2_validation_action_lines(ledger)),
        ("Open Work Items", _work_lines(ledger)),
        ("Contradictions and Reconciliation", _contradiction_lines(ledger)),
        ("Provenance Index", _v2_provenance_lines(ledger)),
        ("Downstream Builder Instructions", _v2_builder_instruction_lines(ledger)),
        ("Known Limits", _known_limits(ledger)),
    ]
    lines = ["# Premise Control Artifact V2", ""]
    for title, body in sections:
        lines.append(f"## {title}")
        lines.append("")
        if body:
            lines.extend(f"- {item}" for item in body)
        else:
            lines.append("None")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _source_summary(ledger: dict[str, Any]) -> str:
    source_hash = ledger.get("source_hash")
    return f"Source hash: {source_hash}" if source_hash else "No source hash recorded."


def _assumption_lines(ledger: dict[str, Any], status: str) -> list[str]:
    return [
        item["statement"]
        for item in ledger.get("assumptions", [])
        if item.get("status") == status
    ]


def _decision_lines(ledger: dict[str, Any], status: str) -> list[str]:
    return [
        item["decision"]
        for item in ledger.get("decisions", [])
        if item.get("status") == status
    ]


def _term_lines(ledger: dict[str, Any]) -> list[str]:
    return [
        f"{item['term']}: {item.get('definition') or 'undefined'}"
        for item in ledger.get("terms", [])
        if item.get("status") in {"provisional", "locked"}
    ]


def _work_lines(ledger: dict[str, Any]) -> list[str]:
    return [
        f"{item['id']} ({item['blast_radius']}, {item['status']}): {item['question']}"
        for item in ledger.get("work_items", [])
        if item.get("status") != "resolved"
    ]


def _risk_register_lines(ledger: dict[str, Any]) -> list[str]:
    return [
        f"{item['id']} ({item['severity']}): {item['statement']}"
        for item in ledger.get("risks", [])
        if item.get("status") == "open"
    ] + [
        f"{item['id']} (high work item): {item['question']}"
        for item in _high_unresolved_work(ledger)
    ]


def _contradiction_lines(ledger: dict[str, Any]) -> list[str]:
    return [
        f"{item['id']} ({item['status']}): {item['description']}"
        for item in ledger.get("contradictions", [])
    ]


def _v2_scope_lines(ledger: dict[str, Any]) -> list[str]:
    frame = ledger.get("session_frame") or {}
    return [
        f"Topic: {_value_or_unset(frame.get('topic'))}",
        f"Downstream use: {_value_or_unset(frame.get('downstream_use'))}",
        f"Closure standard: {_value_or_unset(frame.get('closure_standard'))}",
        f"Input mode: {_value_or_unset(frame.get('input_mode'))}",
        _source_summary(ledger),
    ]


def _v2_closure_lines(ledger: dict[str, Any]) -> list[str]:
    status = _closure_status(ledger)
    lines = [
        f"Mode: {status['mode']}",
        f"Complete: {_yes_no(status['complete'])}",
        f"Intake status: {ledger.get('intake_status', 'not_required')}",
        f"Blind-spot audit status: {ledger.get('blind_spot_audit_status', 'not_run')}",
    ]
    if status.get("force_closed_event"):
        lines.append(f"Force-close event: {status['force_closed_event']}")
    if not status["complete"]:
        lines.append("Closure is controlled incomplete closure, not success.")
    return lines


def _v2_assumption_register_lines(ledger: dict[str, Any], status: str) -> list[str]:
    return [
        _v2_assumption_line(item)
        for item in ledger.get("assumptions", [])
        if item.get("status") == status
    ]


def _v2_unconfirmed_assumption_lines(ledger: dict[str, Any]) -> list[str]:
    return [
        _v2_assumption_line(item)
        for item in ledger.get("assumptions", [])
        if item.get("status") != "locked"
    ]


def _v2_assumption_line(item: dict[str, Any]) -> str:
    dependencies = ", ".join(item.get("depends_on", [])) or "none"
    answers = ", ".join(item.get("user_answer_events", [])) or "none recorded"
    evidence = item.get("evidence_status") or item.get("source_type")
    return (
        f"{item['id']}: {item['statement']} Status: {item.get('status')}. "
        f"Blast radius: {item.get('blast_radius')}. Evidence: {evidence}. "
        f"Dependencies: {dependencies}. Source answer events: {answers}."
    )


def _v2_revision_lines(ledger: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for collection, text_name in (
        ("assumptions", "assumption"),
        ("terms", "term"),
        ("decisions", "decision"),
    ):
        for item in ledger.get(collection, []):
            for entry in item.get("revision_history", []):
                lines.append(
                    f"{item['id']} ({text_name}) revised at {entry['event_id']}: "
                    f"{entry['prior_statement']} -> {entry['new_statement']}"
                )
    return lines


def _v2_open_risk_lines(ledger: dict[str, Any]) -> list[str]:
    lines = _risk_register_lines(ledger)
    evidence_statuses = {
        "external_validation_required",
        "undecidable",
        "open_dependency",
        "unverified_accepted",
    }
    lines.extend(
        f"{item['id']} ({item.get('evidence_status')}): {item['statement']}"
        for item in ledger.get("assumptions", [])
        if item.get("evidence_status") in evidence_statuses
    )
    return lines


def _v2_authority_lines(ledger: dict[str, Any]) -> list[str]:
    authority_terms = ("authority", "authoritative", "owner", "owns", "source of truth", "veto")
    lines = [
        f"{item['id']}: {item['statement']}"
        for item in ledger.get("assumptions", [])
        if _contains_any(item.get("statement", ""), authority_terms)
    ]
    lines.extend(
        f"{item['id']} ({item.get('status')}): {item['question']}"
        for item in ledger.get("work_items", [])
        if item.get("gap_type") == "authority_ownership" and item.get("status") != "resolved"
    )
    if not lines:
        lines.append("No explicit authority statements recorded in the projection.")
    return lines


def _v2_failure_mode_lines(ledger: dict[str, Any]) -> list[str]:
    failure_terms = ("failure", "outage", "reconnect", "gap", "fallback", "retry")
    lines = [
        f"{item['id']}: {item['statement']}"
        for item in ledger.get("assumptions", [])
        if _contains_any(item.get("statement", ""), failure_terms)
    ]
    lines.extend(
        f"{item['id']} ({item.get('status')}): {item['question']}"
        for item in ledger.get("work_items", [])
        if item.get("gap_type") == "failure_mode" and item.get("status") != "resolved"
    )
    if not lines:
        lines.append("No explicit failure-mode declarations recorded in the projection.")
    return lines


def _v2_decision_lines(ledger: dict[str, Any]) -> list[str]:
    return [
        f"{item['id']} ({item.get('status')}): {item['decision']}"
        for item in ledger.get("decisions", [])
    ]


def _v2_exclusion_lines(ledger: dict[str, Any]) -> list[str]:
    excluded_terms = ("excluded", "out of scope", "not in scope")
    lines = [
        f"{item['id']}: {item['statement']}"
        for item in ledger.get("assumptions", [])
        if _contains_any(item.get("statement", ""), excluded_terms)
    ]
    if not lines:
        lines.append("No exclusions recorded in the projection.")
    return lines


def _v2_validation_action_lines(ledger: dict[str, Any]) -> list[str]:
    lines = _external_lines(ledger)
    lines.extend(
        f"{item['id']}: {item['question']}"
        for item in ledger.get("work_items", [])
        if item.get("status") != "resolved" and item.get("blocks_closure")
    )
    lines.extend(
        f"{item['id']}: {item['statement']}"
        for item in _uncarried_external_validation(ledger)
    )
    return _dedupe(lines)


def _v2_provenance_lines(ledger: dict[str, Any]) -> list[str]:
    lines = []
    for item in ledger.get("assumptions", []):
        excerpt = item.get("source_excerpt")
        verified = item.get("source_excerpt_verified")
        origin = item.get("premise_origin") or "unspecified"
        evidence = item.get("evidence_status") or item.get("source_type")
        lines.append(
            f"{item['id']}: origin={origin}, source={item['source_type']}, "
            f"evidence={evidence}, verified={verified}, excerpt={excerpt!r}"
        )
    return lines


def _v2_builder_instruction_lines(ledger: dict[str, Any]) -> list[str]:
    instructions = [
        "Treat the event log and ledger as the source of truth.",
        "Use locked assumptions as authoritative for the audited scope.",
        "Do not treat provisional, model-inferred, undecidable, or externally dependent assumptions as confirmed facts.",
    ]
    if not _closure_status(ledger)["complete"]:
        instructions.append("Do not treat this artifact as complete closure.")
    return instructions


def _external_lines(ledger: dict[str, Any]) -> list[str]:
    lines = [
        f"{item['id']}: {item['statement']}"
        for item in ledger.get("assumptions", [])
        if item.get("source_type") == "external_required"
    ]
    lines.extend(
        f"{item['id']}: {item['question']}"
        for item in ledger.get("work_items", [])
        if item.get("kind") == "validate_external" and item.get("status") != "resolved"
    )
    return lines


def _provenance_lines(ledger: dict[str, Any]) -> list[str]:
    lines = []
    for item in ledger.get("assumptions", []):
        excerpt = item.get("source_excerpt")
        verified = item.get("source_excerpt_verified")
        lines.append(
            f"{item['id']}: {item['source_type']}, verified={verified}, excerpt={excerpt!r}"
        )
    return lines


def _closure_line(ledger: dict[str, Any]) -> str:
    return "force_close" if ledger.get("force_closed") else "not force closed"


def _known_limits(ledger: dict[str, Any]) -> list[str]:
    limits = []
    if _blocking_work_items(ledger):
        limits.append("Unresolved closure-blocking work remains.")
    if ledger.get("protocol_version") == "2.0.0":
        if _unresolved_contradictions(ledger):
            limits.append("Unresolved contradictions remain.")
        if _uncarried_external_validation(ledger):
            limits.append("Outcome-determinative external validation remains.")
    if not limits:
        limits.append("No known limits recorded.")
    return limits


def _blocking_warning_lines(ledger: dict[str, Any]) -> list[str]:
    if ledger.get("protocol_version") == "2.0.0":
        return [
            f"{item['id']}: {item['question']}"
            for item in _blocking_work_items(ledger)
        ]
    return [
        f"{item['id']}: {item['question']}"
        for item in _high_unresolved_work(ledger)
    ]


def _blocking_work_items(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in ledger.get("work_items", [])
        if item.get("blocks_closure") and item.get("status") != "resolved"
    ]


def _high_unresolved_work(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in ledger.get("work_items", [])
        if item.get("blast_radius") == "high" and item.get("status") != "resolved"
    ]


def _open_risk_register(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    risks = [
        {
            "id": item["id"],
            "statement": item["statement"],
            "severity": item["severity"],
        }
        for item in ledger.get("risks", [])
        if item.get("status") == "open"
    ]
    risks.extend(
        {
            "id": item["id"],
            "statement": item["question"],
            "severity": item.get("blast_radius", "high"),
            "source": "unresolved_high_blast_radius_work",
        }
        for item in (
            _blocking_work_items(ledger)
            if ledger.get("protocol_version") == "2.0.0"
            else _high_unresolved_work(ledger)
        )
    )
    return risks


def _traceability_summary(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "entity_id": item["id"],
            "source": item.get("source_type"),
            "verified": item.get("source_excerpt_verified"),
        }
        for item in ledger.get("assumptions", [])
        if item.get("status") == "locked"
    ]


def _assert_artifact_eligible(ledger: dict[str, Any]) -> None:
    if ledger.get("protocol_version") != "2.0.0":
        blockers = _blocking_work_items(ledger)
        if blockers and not ledger.get("force_closed"):
            raise OperationError(
                "generate-artifact requires no unresolved closure blockers or FORCE_CLOSED"
            )
        return

    if ledger.get("blind_spot_audit_status") != "complete":
        raise OperationError(
            "V2 generate-artifact requires a completed blind-spot audit"
        )
    if ledger.get("force_closed"):
        return
    if ledger.get("intake_status") not in {"complete", "not_required"}:
        raise OperationError("V2 generate-artifact requires completed intake")
    active = _active_work_items(ledger)
    if active:
        raise OperationError(
            "V2 generate-artifact requires no active work items: "
            + ", ".join(item["id"] for item in active)
        )
    blockers = _blocking_work_items(ledger)
    if blockers:
        raise OperationError(
            "V2 generate-artifact requires no unresolved closure blockers: "
            + ", ".join(item["id"] for item in blockers)
        )
    contradictions = _unresolved_contradictions(ledger)
    if contradictions:
        raise OperationError(
            "V2 generate-artifact requires no unresolved contradictions: "
            + ", ".join(item["id"] for item in contradictions)
        )
    external = _uncarried_external_validation(ledger)
    if external:
        raise OperationError(
            "V2 generate-artifact requires outcome-determinative external validation "
            "to be carried as open risk or force-close incompleteness: "
            + ", ".join(item["id"] for item in external)
        )


def _closure_status(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "force_closed" if ledger.get("force_closed") else "open",
        "complete": not _v2_incomplete_reasons(ledger),
        "force_closed_event": ledger.get("force_closed_event") if ledger.get("force_closed") else None,
    }


def _v2_incomplete_reasons(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        _blocking_work_items(ledger)
        + _unresolved_contradictions(ledger)
        + _uncarried_external_validation(ledger)
    )


def _active_work_items(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in ledger.get("work_items", [])
        if item.get("status") == "active"
    ]


def _unresolved_contradictions(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in ledger.get("contradictions", [])
        if item.get("status") == "open"
    ]


def _uncarried_external_validation(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    statuses = {
        "external_validation_required",
        "undecidable",
        "open_dependency",
    }
    carried = {
        ref
        for risk in ledger.get("risks", [])
        if risk.get("status") == "open"
        for ref in risk.get("source_refs", [])
    }
    return [
        item
        for item in ledger.get("assumptions", [])
        if item.get("blast_radius") == "high"
        and item.get("evidence_status") in statuses
        and item.get("id") not in carried
    ]


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _value_or_unset(value: Any) -> str:
    if value is None or value == "":
        return "not recorded"
    return str(value)


def _yes_no(value: bool) -> str:
    return "true" if value else "false"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
