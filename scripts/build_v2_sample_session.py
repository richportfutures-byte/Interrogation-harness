#!/usr/bin/env python3
"""Build the canonical V2 sample session through real harness operations."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from interrogation_harness import canonical
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import EventType
from interrogation_harness.interrogation import OperationError
from interrogation_harness.model import DeterministicMockModel, ModelJob
from interrogation_harness.model.adapter import ModelRequest
from interrogation_harness.operations import HarnessOperations
from interrogation_harness.session_store import SessionStore

DEFAULT_SESSION_ID = "v2_sample_session"
DEFAULT_SESSION_ROOT = ROOT / "sessions"
FIXED_TIME = "2026-01-01T00:00:00Z"

SOURCE_MARKDOWN = """# Trading Risk Gate Notes

Trading signals are derived from the market data stream.

The execution gateway owns order placement.

The risk gate can veto orders before they reach the gateway.

Operators may force close incomplete handoffs when unresolved blockers remain visible.

Unknowns:

- Manual override ownership during reconnect is not specified.
- Feed gap reconnect behavior still requires validation against venue rules.
"""


class V2SampleMockModel(DeterministicMockModel):
    """Deterministic V2 model tailored to the canonical sample source."""

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        if request.job == ModelJob.INTAKE_UNSTRUCTURED_INPUT:
            return _raw(_intake())
        if request.job == ModelJob.RANK_NEXT_WORK_ITEM:
            return _raw(_rank_next(request.payload.get("projection")))
        if request.job == ModelJob.BLIND_SPOT_AUDIT:
            return _raw(_blind_spot_audit())
        return super().complete(request, scenario=scenario)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    session_root = Path(args.root)
    session_id = args.session_id
    session_dir = session_root / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)

    ops = HarnessOperations(
        session_root,
        session_id,
        model=V2SampleMockModel(),
        now=lambda: FIXED_TIME,
    )
    ops.create_session(
        protocol_version="2.0.0",
        session_frame={
            "topic": "trading risk gate",
            "downstream_use": "implementation handoff",
            "closure_standard": "locked authority and failure behavior or explicit incomplete closure",
            "input_mode": "unstructured",
        },
    )
    ops.add_source(SOURCE_MARKDOWN)
    intake = ops.run_intake()
    _require(intake.accepted, "V2 intake failed")

    active = ops.ask_next()
    _require(active["id"] == "W-0001", "expected W-0001 first")
    confirmed = ops.answer("confirm")
    _require(confirmed.accepted, "confirm answer failed")

    audit = ops.run_blind_spot_audit()
    _require(audit["accepted"], "blind-spot audit failed")
    try:
        ops.generate_artifact()
    except OperationError:
        pass
    else:
        raise AssertionError("normal V2 artifact unexpectedly succeeded with blockers")

    ledger = ops.force_close(reason="canonical V2 sample controlled incomplete closure")
    _require(ledger["force_closed"] is True, "sample is not force closed")
    artifact = ops.generate_artifact()
    _require(artifact["accepted"], "V2 artifact generation failed")

    final_ledger = ops.store.read_ledger()
    _verify_sample(ops, final_ledger, session_root, session_id)
    print(f"rebuilt {(session_root / session_id).relative_to(ROOT) if session_root.is_relative_to(ROOT) else session_root / session_id}")
    return 0


def _parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_SESSION_ROOT))
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    return parser.parse_args(argv)


def _raw(obj: dict[str, Any]) -> str:
    return canonical.dumps_event_line(obj)


def _intake() -> dict[str, Any]:
    return {
        "session_frame": {
            "topic": "trading risk gate",
            "downstream_use": "implementation handoff",
            "closure_standard": "locked authority and failure behavior or explicit incomplete closure",
            "input_mode": "unstructured",
        },
        "assumptions": [
            {
                "tmp_handle": "tmp_assumption_1",
                "intake_label": "CA-01",
                "statement": "Trading signals are derived from the market data stream.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": "Trading signals are derived from the market data stream.",
                "blast_radius": "high",
                "downstream_impact": "Signal authority and trading decisions",
                "risk_if_wrong": "Orders may be generated from the wrong market input",
                "evidence_status": "verified_user_stated",
            },
            {
                "tmp_handle": "tmp_assumption_2",
                "intake_label": "CA-02",
                "statement": "The execution gateway owns order placement.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": "The execution gateway owns order placement.",
                "blast_radius": "high",
                "downstream_impact": "Order authority boundary",
                "risk_if_wrong": "Signals and execution may both appear authoritative",
                "evidence_status": "verified_user_stated",
            },
            {
                "tmp_handle": "tmp_assumption_3",
                "intake_label": "CA-03",
                "statement": "Manual override ownership during reconnect is not specified.",
                "status": "candidate",
                "source_type": "model_inferred",
                "source_excerpt": None,
                "blast_radius": "high",
                "downstream_impact": "Human override path",
                "risk_if_wrong": "Operators may bypass or duplicate risk decisions",
                "evidence_status": "model_inferred",
            },
        ],
        "work_items": [
            {
                "tmp_handle": "tmp_work_1",
                "derived_question_label": "DQ-01",
                "kind": "resolve_assumption",
                "question": "Confirm that trading signals are derived from the market data stream.",
                "why_it_matters": "It defines signal authority.",
                "what_breaks_if_wrong": "The implementation may use the wrong upstream source.",
                "blast_radius": "high",
                "blocks_closure": True,
                "gap_type": "authority_ownership",
                "source_assumption_refs": ["tmp_assumption_1"],
                "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
            },
            {
                "tmp_handle": "tmp_work_2",
                "derived_question_label": "DQ-02",
                "kind": "clarify",
                "question": "Who owns manual override decisions during reconnect?",
                "why_it_matters": "It controls the human override path.",
                "what_breaks_if_wrong": "Operators may override the wrong authority boundary.",
                "blast_radius": "high",
                "blocks_closure": True,
                "gap_type": "authority_ownership",
                "source_assumption_refs": ["tmp_assumption_3"],
                "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
            },
        ],
        "risks": [],
        "terms": [
            {
                "tmp_handle": "tmp_term_1",
                "term": "risk gate",
                "definition": "The component that can veto orders before execution.",
                "status": "provisional",
            }
        ],
        "decisions": [],
        "contradictions": [],
    }


def _rank_next(projection: Any) -> dict[str, Any]:
    work_items = _mapping_get(projection, "work_items") or []
    candidates = [
        item
        for item in work_items
        if _mapping_get(item, "status") in {"open", "deferred", "blocked"}
    ]
    blockers = [item for item in candidates if _mapping_get(item, "blocks_closure")]
    selected = sorted(blockers or candidates, key=lambda item: _mapping_get(item, "id"))[0]
    return {
        "selected_work_item_id": selected["id"],
        "question": selected["question"],
        "why_it_matters": selected["why_it_matters"],
        "what_breaks_if_wrong": selected["what_breaks_if_wrong"],
        "tested_entity_id": selected.get("target_entity")
        or (selected.get("source_assumption_ids") or [None])[0],
        "recommended_default": None,
        "recommended_default_basis": None,
        "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
    }


def _blind_spot_audit() -> dict[str, Any]:
    return {
        "findings": [
            {
                "category": "feed_gap_reconnect_semantics",
                "refs": ["A-0001"],
                "severity": "high",
                "description": "Feed gap reconnect behavior requires external validation.",
                "conversion_target": "assumption",
                "assumption": {
                    "statement": "Feed gap reconnect behavior requires external validation against venue rules.",
                    "status": "candidate",
                    "source_type": "external_required",
                    "source_excerpt": None,
                    "blast_radius": "high",
                    "downstream_impact": "Market data recovery and order safety",
                    "risk_if_wrong": "Orders may resume from stale or incomplete market state",
                    "evidence_status": "external_validation_required",
                    "external_fact": "Venue reconnect and gap-fill rules",
                    "depends_on": ["A-0001"],
                },
            },
            {
                "category": "human_override_path",
                "refs": ["A-0003"],
                "severity": "high",
                "description": "Human override authority is unresolved during reconnect.",
                "conversion_target": "work_item",
                "blocks_closure": True,
                "work_item": {
                    "kind": "clarify",
                    "question": "Who can override the risk gate during reconnect?",
                    "why_it_matters": "It defines the human override path.",
                    "what_breaks_if_wrong": "Manual action can bypass risk ownership.",
                    "blast_radius": "high",
                    "blocks_closure": True,
                    "gap_type": "authority_ownership",
                    "related_refs": ["A-0003"],
                    "source_assumption_refs": ["A-0003"],
                    "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
                },
            },
        ],
        "missing_provenance": [],
        "invalid_source_excerpts": [],
        "unresolved_material_work": [],
        "artifact_blockers": [],
    }


def _verify_sample(
    ops: HarnessOperations,
    ledger: dict[str, Any],
    session_root: Path,
    session_id: str,
) -> None:
    events = ops.event_log.read_events()
    artifact_text = ops.store.artifact_path.read_text(encoding="utf-8")
    _require(ledger["protocol_version"] == "2.0.0", "sample is not V2")
    _require(ledger["intake_status"] == "complete", "intake did not complete")
    _require(ledger["blind_spot_audit_status"] == "complete", "audit did not complete")
    _require(ledger["force_closed"] is True, "force close missing")
    _require(
        any(
            event["event_type"] == "AUDIT_RUN"
            and event["payload"].get("audit_type") == "blind_spot"
            for event in events
        ),
        "blind-spot AUDIT_RUN missing",
    )
    _require(
        any(item.get("premise_origin") == "blind_spot" for item in ledger["assumptions"]),
        "blind-spot assumption missing",
    )
    _require(
        any(
            item["status"] != "resolved" and item.get("blocks_closure")
            for item in ledger["work_items"]
        ),
        "unresolved closure blocker missing",
    )
    _require("# Premise Control Artifact V2" in artifact_text, "V2 artifact title missing")
    for section in (
        "## Scope and Objective",
        "## Closure Status",
        "## Locked Assumptions",
        "## Open Risks and Undecidable Assumptions",
        "## Authority Map",
        "## Failure-Mode Declarations",
        "## Validation Actions Still Required",
    ):
        _require(section in artifact_text, f"artifact missing {section}")
    _require("Closure is controlled incomplete closure" in artifact_text, "incomplete closure not visible")
    _require("Feed gap reconnect behavior requires external validation" in artifact_text, "external validation missing")
    store = SessionStore(session_root, session_id)
    log = EventLog(store)
    rebuilt = canonical.dumps_ledger(ops.projector.project(log.read_events()))
    _require(rebuilt == store.ledger_path.read_text(encoding="utf-8"), "ledger is not rebuild stable")


def _mapping_get(value: Any, key: str) -> Any:
    return value.get(key) if hasattr(value, "get") else None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
