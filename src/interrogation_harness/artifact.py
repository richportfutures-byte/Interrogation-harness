"""Projection-only final artifact generation."""

from __future__ import annotations

from typing import Any

from interrogation_harness import canonical
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
        blockers = _blocking_work_items(ledger)
        if blockers and not ledger.get("force_closed"):
            raise ValueError("generate-artifact requires no unresolved closure blockers or FORCE_CLOSED")

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
            request_payload={"projection": ledger, "closure_mode": "force_close"},
        )
        if not result.accepted or result.parsed_output is None:
            raise ValueError("; ".join(result.errors) or "artifact_generation rejected")
        self.ops.store.write_artifact(result.parsed_output["artifact_markdown"])
        return {"accepted": True, "artifact_path": self.ops.store.artifact_path, "ledger": self.ops.ledger()}


def _artifact_output(ledger: dict[str, Any]) -> dict[str, Any]:
    markdown = _artifact_markdown(ledger)
    return {
        "artifact_markdown": markdown,
        "blocking_warnings": [
            f"{item['id']}: {item['question']}"
            for item in _high_unresolved_work(ledger)
        ],
        "open_risk_register": _open_risk_register(ledger),
        "traceability_summary": _traceability_summary(ledger),
    }


def _artifact_markdown(ledger: dict[str, Any]) -> str:
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
    if not limits:
        limits.append("No known limits recorded.")
    return limits


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
            "severity": "high",
            "source": "unresolved_high_blast_radius_work",
        }
        for item in _high_unresolved_work(ledger)
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
