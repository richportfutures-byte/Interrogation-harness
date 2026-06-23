#!/usr/bin/env python3
"""Build the committed sample session through the real harness operations."""

from __future__ import annotations

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
from interrogation_harness.model import DeterministicMockModel, ModelJob
from interrogation_harness.model.adapter import ModelRequest
from interrogation_harness.operations import HarnessOperations
from interrogation_harness.session_store import SessionStore
from interrogation_harness.validation import ModelContractValidator

SESSION_ID = "sample_session"
SESSION_ROOT = ROOT / "sessions"
SESSION_DIR = SESSION_ROOT / SESSION_ID
FIXED_TIME = "2026-01-01T00:00:00Z"

SOURCE_MARKDOWN = """# Messy Payment Harness Notes

We need the payment system to be implementation grade, but these notes are uneven.

Payments require idempotency keys.

The billing worker owns payment writes.

Operators may force close a handoff, but unresolved high-risk questions must stay visible.

Unknowns:

- The exact retry limit is not confirmed.
- The processor outage behavior still needs a decision.
"""


class SampleMockModel(DeterministicMockModel):
    """Deterministic offline model tailored to the sample source."""

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        if request.job == ModelJob.INITIAL_EXTRACTION:
            return _raw(_initial_extraction())
        if request.job == ModelJob.RANK_NEXT_WORK_ITEM:
            return _raw(_rank_next(request.payload.get("projection")))
        return super().complete(request, scenario=scenario)


def main() -> int:
    if SESSION_DIR.exists():
        shutil.rmtree(SESSION_DIR)

    ops = HarnessOperations(
        SESSION_ROOT,
        SESSION_ID,
        model=SampleMockModel(),
        now=lambda: FIXED_TIME,
    )
    ops.create_session()
    ops.add_source(SOURCE_MARKDOWN)
    extraction = ops.run_initial_extraction()
    _require(extraction.accepted, "initial extraction failed")

    active = ops.ask_next()
    _require(active["id"] == "W-0001", "expected W-0001 first")
    unknown = ops.answer("unknown")
    _require(unknown.accepted, "unknown answer failed")

    deferred = ops.defer("W-0002", reason="processor behavior decision deferred")
    _require(deferred["status"] == "deferred", "W-0002 was not deferred")

    active = ops.ask_next()
    _require(active["id"] == "W-0003", "expected W-0003 after deferred work")
    confirmed = ops.answer("confirm")
    _require(confirmed.accepted, "confirm for W-0003 failed")

    revised = ops.revise(
        "A-0003",
        "The billing worker owns payment write orchestration.",
        reason="clarified ownership wording",
    )
    _require(revised["status"] == "revised", "A-0003 was not revised")

    active = ops.ask_next()
    _require(active["id"] == "W-0004", "expected W-0004 for locked assumption")
    locked = ops.answer("confirm")
    _require(locked.accepted, "confirm for W-0004 failed")

    _record_illegal_transition(ops)
    ops.force_close(reason="sample session force close")
    artifact = ops.generate_artifact()
    _require(artifact["accepted"], "artifact generation failed")

    ledger = ops.store.read_ledger()
    _verify_section_24(ops, ledger)
    print(f"rebuilt {SESSION_DIR.relative_to(ROOT)}")
    return 0


def _record_illegal_transition(ops: HarnessOperations) -> None:
    illegal = _raw(
        {
            "proposed_events": [
                {
                    "event_type": "ASSUMPTION_TRANSITIONED",
                    "target_ref": "A-0004",
                    "payload": {
                        "from": "locked",
                        "to": "rejected",
                        "reason": "sample illegal locked overwrite",
                    },
                }
            ],
            "followup_required": False,
            "warnings": [],
        }
    )
    result = ModelContractValidator(ops.event_log, _OneShotModel(illegal), ops.projector).run(
        ModelJob.INTERPRET_USER_ANSWER,
        session_id=SESSION_ID,
        correlation_id="sample-illegal-transition",
        idempotency_key="sample-illegal-transition",
        timestamp=FIXED_TIME,
        request_payload={},
        source_markdown=SOURCE_MARKDOWN,
    )
    _require(not result.accepted, "illegal transition was accepted")


class _OneShotModel:
    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output

    def complete(self, request: ModelRequest, *, scenario: str | None = None) -> str:
        return self.raw_output


def _initial_extraction() -> dict[str, Any]:
    return {
        "assumptions": [
            {
                "tmp_handle": "tmp_assumption_1",
                "statement": "Payments require idempotency keys.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": "Payments require idempotency keys.",
                "blast_radius": "high",
                "downstream_impact": "Payment retry behavior",
                "risk_if_wrong": "Duplicate payment writes",
            },
            {
                "tmp_handle": "tmp_assumption_2",
                "statement": "The processor outage behavior needs an explicit decision.",
                "status": "candidate",
                "source_type": "model_inferred",
                "source_excerpt": None,
                "blast_radius": "medium",
                "downstream_impact": "Operational resilience",
                "risk_if_wrong": "Incomplete incident behavior",
            },
            {
                "tmp_handle": "tmp_assumption_3",
                "statement": "The billing worker owns payment writes.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": "The billing worker owns payment writes.",
                "blast_radius": "medium",
                "downstream_impact": "Service ownership",
                "risk_if_wrong": "Wrong component receives write responsibility",
            },
            {
                "tmp_handle": "tmp_assumption_4",
                "statement": "Unresolved high-risk questions must stay visible after force close.",
                "status": "candidate",
                "source_type": "user_stated",
                "source_excerpt": "unresolved high-risk questions must stay visible",
                "blast_radius": "high",
                "downstream_impact": "Handoff safety",
                "risk_if_wrong": "The artifact may hide unresolved risk",
            },
        ],
        "work_items": [
            _work(
                "tmp_work_1",
                "tmp_assumption_1",
                "Should payment retries be idempotent?",
                "Duplicate payment writes are high impact.",
                "A retry can create duplicate payments.",
                "high",
            ),
            _work(
                "tmp_work_2",
                "tmp_assumption_2",
                "What should happen during processor outages?",
                "Incident behavior affects operations.",
                "Operators may infer the wrong outage behavior.",
                "medium",
            ),
            _work(
                "tmp_work_3",
                "tmp_assumption_3",
                "Does the billing worker own payment write orchestration?",
                "Ownership shapes implementation boundaries.",
                "The wrong service may own payment writes.",
                "medium",
            ),
            _work(
                "tmp_work_4",
                "tmp_assumption_4",
                "Must unresolved high-risk questions stay visible after force close?",
                "Closure must not hide unresolved risk.",
                "A downstream builder may trust an unsafe artifact.",
                "high",
            ),
        ],
        "risks": [],
        "terms": [],
        "decisions": [],
        "contradictions": [],
    }


def _work(
    handle: str,
    assumption_handle: str,
    question: str,
    why: str,
    breaks: str,
    blast_radius: str,
) -> dict[str, Any]:
    return {
        "tmp_handle": handle,
        "kind": "resolve_assumption",
        "question": question,
        "why_it_matters": why,
        "what_breaks_if_wrong": breaks,
        "blast_radius": blast_radius,
        "blocks_closure": blast_radius == "high",
        "related_temp_refs": [assumption_handle],
        "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
    }


def _rank_next(projection: Any) -> dict[str, Any]:
    work_items = _mapping_get(projection, "work_items") or []
    open_items = [item for item in work_items if _mapping_get(item, "status") == "open"]
    if not open_items:
        open_items = [item for item in work_items if _mapping_get(item, "status") == "deferred"]
    selected = sorted(open_items, key=lambda item: _mapping_get(item, "id"))[0]
    return {
        "selected_work_item_id": selected["id"],
        "question": selected["question"],
        "why_it_matters": selected["why_it_matters"],
        "what_breaks_if_wrong": selected["what_breaks_if_wrong"],
        "tested_entity_id": selected["target_entity"],
        "recommended_default": None,
        "recommended_default_basis": None,
        "allowed_answers": ["confirm", "reject", "revise", "defer", "unknown"],
    }


def _verify_section_24(ops: HarnessOperations, ledger: dict[str, Any]) -> None:
    events = ops.event_log.read_events()
    artifact_text = ops.store.artifact_path.read_text(encoding="utf-8")

    created_assumptions = [
        event
        for event in events
        if event["event_type"] == "ASSUMPTION_CREATED"
        and event["payload"].get("status") == "candidate"
    ]
    _require(len(created_assumptions) >= 3, "missing three candidate assumptions")
    _require(
        any(item["source_type"] == "model_inferred" for item in ledger["assumptions"]),
        "missing model_inferred assumption",
    )
    _require(
        any(
            item["source_type"] == "user_stated"
            and item.get("source_excerpt_verified") is True
            for item in ledger["assumptions"]
        ),
        "missing verified user_stated assumption",
    )
    _require(
        any(item["blast_radius"] == "high" for item in ledger["work_items"]),
        "missing high blast radius work item",
    )
    _require(
        any(item["status"] == "open" for item in ledger["risks"]),
        "missing open risk from unknown answer",
    )
    _require(
        any(item["status"] == "deferred" for item in ledger["work_items"]),
        "missing deferred work item",
    )
    _require(
        any(item["status"] == "revised" for item in ledger["assumptions"]),
        "missing revised assumption",
    )
    _require(
        any(event["event_type"] == "PROPOSAL_REJECTED" for event in events),
        "missing rejected illegal transition",
    )
    _require(ledger["force_closed"] is True, "sample is not force closed")
    _require(ops.store.artifact_path.exists(), "final_artifact.md missing")
    _require("## Locked Assumptions" in artifact_text, "artifact missing locked assumptions")
    _require("## Open Risk Register" in artifact_text, "artifact missing open risk register")
    _require("## Provenance Index" in artifact_text, "artifact missing provenance")
    _require(
        "## Downstream Builder Instructions" in artifact_text,
        "artifact missing downstream builder instructions",
    )
    _require("## Closure Mode" in artifact_text, "artifact missing closure mode")
    _require("## Known Limits" in artifact_text, "artifact missing known limits")
    _require(
        any(
            item["blast_radius"] == "high" and item["status"] != "resolved"
            for item in ledger["work_items"]
        ),
        "unresolved high blast radius work was not preserved",
    )
    locked = {
        item["statement"] for item in ledger["assumptions"] if item["status"] == "locked"
    }
    for bullet in _section_bullets(artifact_text, "Locked Assumptions"):
        _require(bullet in locked, f"artifact invented locked assumption: {bullet}")

    store = SessionStore(SESSION_ROOT, SESSION_ID)
    log = EventLog(store)
    rebuilt = canonical.dumps_ledger(log and ops.projector.project(log.read_events()))
    _require(
        rebuilt == store.ledger_path.read_text(encoding="utf-8"),
        "ledger is not rebuild stable",
    )


def _section_bullets(markdown: str, title: str) -> list[str]:
    bullets: list[str] = []
    in_section = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == f"## {title}"
            continue
        if in_section and stripped.startswith("- "):
            bullets.append(stripped[2:])
    return bullets


def _mapping_get(value: Any, key: str) -> Any:
    return value.get(key) if hasattr(value, "get") else None


def _raw(obj: dict[str, Any]) -> str:
    return canonical.dumps_event_line(obj)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
