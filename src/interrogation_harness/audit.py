"""Audit engine and deterministic conversion of audit findings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from interrogation_harness.events import Actor, EventType
from interrogation_harness.ids import IdAllocator
from interrogation_harness.interrogation import OperationError
from interrogation_harness.model.adapter import ModelJob
from interrogation_harness.provenance import apply_assumption_provenance
from interrogation_harness.validation import _finalize_evidence_status


class AuditEngine:
    """Run protocol-aware audits through validation, then convert findings."""

    def __init__(self, operations) -> None:
        self.ops = operations

    def run_audit(self, *, operation_name: str = "run-audit") -> dict[str, Any]:
        if self.ops.protocol_version() == "2.0.0":
            return self.run_blind_spot_audit(operation_name=operation_name)
        return self._run_contradiction_audit(operation_name=operation_name)

    def _run_contradiction_audit(self, *, operation_name: str) -> dict[str, Any]:
        source = self.ops.store.read_source() if self.ops.store.source_exists() else ""
        payload = {
            "session_id": self.ops.session_id,
            "source_markdown": source,
            "projection": self.ops.ledger(),
        }
        ids = self.ops.op_ids(operation_name, payload)
        result = self.ops.validator().run(
            ModelJob.CONTRADICTION_AUDIT,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload=payload,
            source_markdown=source,
        )
        if not result.accepted or result.parsed_output is None:
            return {"accepted": False, "errors": result.errors}
        self._convert_contradiction_findings(result.parsed_output, ids)
        return {"accepted": True, "ledger": self.ops.rebuild_ledger(), "findings": result.parsed_output}

    def run_blind_spot_audit(self, *, operation_name: str = "run-blind-spot-audit") -> dict[str, Any]:
        ledger = self.ops.ledger()
        if ledger.get("protocol_version") != "2.0.0":
            raise OperationError("run-blind-spot-audit requires a V2 session")
        if ledger.get("intake_status") != "complete":
            raise OperationError("blind-spot audit requires completed V2 intake")
        active = [
            item
            for item in ledger.get("work_items", [])
            if item.get("status") == "active"
        ]
        if active:
            active_ids = ", ".join(item["id"] for item in active)
            raise OperationError(
                f"blind-spot audit requires no active work items: {active_ids}"
            )
        payload = {
            "session_id": self.ops.session_id,
            "projection": ledger,
            "audit_type": "blind_spot",
            "categories": _BLIND_SPOT_CATEGORIES,
        }
        ids = self.ops.op_ids(operation_name, payload)
        result = self.ops.validator().run(
            ModelJob.BLIND_SPOT_AUDIT,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload=payload,
            source_markdown=self.ops.store.read_source() if self.ops.store.source_exists() else "",
        )
        if not result.accepted or result.parsed_output is None:
            return {"accepted": False, "errors": result.errors}
        self._convert_blind_spot_findings(
            result.parsed_output,
            ids,
            source_markdown=self.ops.store.read_source() if self.ops.store.source_exists() else "",
        )
        return {
            "accepted": True,
            "ledger": self.ops.rebuild_ledger(),
            "findings": result.parsed_output,
        }

    def force_close(self, reason: str = "force close requested") -> dict[str, Any]:
        audit_result = self.run_audit(operation_name="force-close-audit")
        if not audit_result.get("accepted"):
            raise ValueError("force-close audit failed")
        ids = self.ops.op_ids("force-close", {"reason": reason, "projection": self.ops.ledger()})
        ledger = self.ops.ledger()
        if not ledger.get("force_closed"):
            self.ops.event_log.append(
                event_type=EventType.FORCE_CLOSED,
                actor=Actor.HARNESS,
                session_id=self.ops.session_id,
                correlation_id=ids.correlation_id,
                idempotency_key=ids.idempotency_key,
                timestamp=ids.timestamp,
                payload={"reason": reason},
            )
        return self.ops.rebuild_ledger()

    def _convert_contradiction_findings(self, parsed: dict[str, Any], ids) -> None:
        ledger = self.ops.ledger()
        existing = {
            (tuple(item.get("refs", [])), item.get("description", ""))
            for item in ledger.get("contradictions", [])
        }
        allocator = IdAllocator.from_ledger(ledger)
        index = 1
        for finding in parsed.get("findings", []):
            if finding.get("kind") != "contradiction":
                continue
            key = (tuple(finding.get("refs", [])), finding.get("description", ""))
            if key in existing:
                continue
            ref_map = allocator.allocate(
                [f"tmp_contradiction_audit_{index}", f"tmp_work_audit_{index}"]
            )
            contradiction_id = ref_map[f"tmp_contradiction_audit_{index}"]
            work_id = ref_map[f"tmp_work_audit_{index}"]
            severity = finding.get("severity", "medium")
            self.ops.event_log.append(
                event_type=EventType.CONTRADICTION_CREATED,
                actor=Actor.HARNESS,
                session_id=self.ops.session_id,
                correlation_id=ids.correlation_id,
                idempotency_key=ids.idempotency_key,
                timestamp=ids.timestamp,
                payload={
                    "id": contradiction_id,
                    "refs": list(finding.get("refs", [])),
                    "severity": severity,
                    "description": finding.get("description", ""),
                    "status": "open",
                    "resolution_work_item": work_id,
                },
                ref_map={f"tmp_contradiction_audit_{index}": contradiction_id},
            )
            self.ops.event_log.append(
                event_type=EventType.WORK_ITEM_CREATED,
                actor=Actor.HARNESS,
                session_id=self.ops.session_id,
                correlation_id=ids.correlation_id,
                idempotency_key=ids.idempotency_key,
                timestamp=ids.timestamp,
                payload={
                    "id": work_id,
                    "kind": "resolve_contradiction",
                    "status": "open",
                    "question": f"Resolve contradiction: {finding.get('description', '')}",
                    "why_it_matters": "Contradictions block reliable implementation.",
                    "what_breaks_if_wrong": "Downstream builders may receive incompatible facts.",
                    "blast_radius": severity,
                    "blocks_closure": severity == "high",
                    "target_entity": contradiction_id,
                    "answer_options": ["revise", "defer", "unknown"],
                },
                ref_map={f"tmp_work_audit_{index}": work_id},
            )
            existing.add(key)
            index += 1

    def _convert_blind_spot_findings(
        self,
        parsed: dict[str, Any],
        ids,
        *,
        source_markdown: str,
    ) -> None:
        ledger = self.ops.ledger()
        allocator = IdAllocator.from_ledger(ledger)
        existing = _existing_conversion_keys(ledger)
        index = 1
        for finding in parsed.get("findings", []):
            target = finding.get("conversion_target")
            if target == "no_op":
                continue
            if target == "work_item":
                self._convert_blind_spot_work_item(finding, ids, allocator, existing, index)
            elif target == "risk":
                self._convert_blind_spot_risk(finding, ids, allocator, existing, index)
            elif target == "contradiction":
                self._convert_blind_spot_contradiction(finding, ids, allocator, existing, index)
            elif target == "assumption":
                self._convert_blind_spot_assumption(
                    finding, ids, allocator, existing, index, source_markdown=source_markdown
                )
            index += 1

    def _convert_blind_spot_work_item(
        self,
        finding: dict[str, Any],
        ids,
        allocator: IdAllocator,
        existing: dict[str, set[tuple]],
        index: int,
    ) -> None:
        proposal = finding["work_item"]
        payload = _work_item_payload(finding, proposal)
        key = _work_key(payload)
        if key in existing["work_item"]:
            return
        handle = f"tmp_work_blind_spot_{index}"
        ref_map = allocator.allocate([handle])
        payload["id"] = ref_map[handle]
        self._append_creation(EventType.WORK_ITEM_CREATED, payload, ids, handle, ref_map)
        existing["work_item"].add(key)

    def _convert_blind_spot_risk(
        self,
        finding: dict[str, Any],
        ids,
        allocator: IdAllocator,
        existing: dict[str, set[tuple]],
        index: int,
    ) -> None:
        proposal = finding["risk"]
        payload = deepcopy(proposal)
        payload["source_refs"] = list(proposal.get("source_refs", finding.get("refs", [])))
        key = (tuple(payload["source_refs"]), payload.get("statement", ""))
        if key in existing["risk"]:
            return
        handle = f"tmp_risk_blind_spot_{index}"
        ref_map = allocator.allocate([handle])
        payload["id"] = ref_map[handle]
        self._append_creation(EventType.RISK_CREATED, payload, ids, handle, ref_map)
        existing["risk"].add(key)

    def _convert_blind_spot_contradiction(
        self,
        finding: dict[str, Any],
        ids,
        allocator: IdAllocator,
        existing: dict[str, set[tuple]],
        index: int,
    ) -> None:
        proposal = finding["contradiction"]
        contradiction = deepcopy(proposal)
        contradiction["refs"] = list(proposal.get("refs", finding.get("refs", [])))
        c_key = (tuple(contradiction["refs"]), contradiction.get("description", ""))
        if c_key in existing["contradiction"]:
            return
        c_handle = f"tmp_contradiction_blind_spot_{index}"
        w_handle = f"tmp_work_blind_spot_contradiction_{index}"
        ref_map = allocator.allocate([c_handle, w_handle])
        contradiction["id"] = ref_map[c_handle]
        contradiction["resolution_work_item"] = ref_map[w_handle]
        self._append_creation(EventType.CONTRADICTION_CREATED, contradiction, ids, c_handle, ref_map)
        severity = contradiction.get("severity", finding.get("severity", "medium"))
        work = {
            "id": ref_map[w_handle],
            "kind": "resolve_contradiction",
            "status": "open",
            "question": f"Resolve blind-spot contradiction: {contradiction.get('description', '')}",
            "why_it_matters": "Blind-spot contradictions block reliable closure.",
            "what_breaks_if_wrong": "The artifact can carry incompatible implementation facts.",
            "blast_radius": severity,
            "blocks_closure": severity in {"high", "medium"},
            "target_entity": ref_map[c_handle],
            "gap_type": "contradiction",
            "source_assumption_ids": [ref for ref in contradiction["refs"] if ref.startswith("A-")],
            "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
        }
        if severity == "medium":
            work["blocking_reason"] = "Audit-created contradiction requires reconciliation."
        self._append_creation(EventType.WORK_ITEM_CREATED, work, ids, w_handle, ref_map)
        existing["contradiction"].add(c_key)
        existing["work_item"].add(_work_key(work))

    def _convert_blind_spot_assumption(
        self,
        finding: dict[str, Any],
        ids,
        allocator: IdAllocator,
        existing: dict[str, set[tuple]],
        index: int,
        *,
        source_markdown: str,
    ) -> None:
        proposal = finding["assumption"]
        payload = deepcopy(proposal)
        payload = apply_assumption_provenance(payload, source_markdown)
        payload = _finalize_evidence_status(payload)
        payload["premise_origin"] = "blind_spot"
        payload["depends_on"] = list(proposal.get("depends_on", finding.get("refs", [])))
        key = (payload.get("statement", ""), tuple(payload["depends_on"]))
        if key in existing["assumption"]:
            return
        handle = f"tmp_assumption_blind_spot_{index}"
        ref_map = allocator.allocate([handle])
        payload["id"] = ref_map[handle]
        self._append_creation(EventType.ASSUMPTION_CREATED, payload, ids, handle, ref_map)
        existing["assumption"].add(key)

    def _append_creation(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        ids,
        handle: str,
        ref_map: dict[str, str],
    ) -> None:
        self.ops.event_log.append(
            event_type=event_type,
            actor=Actor.HARNESS,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            payload=payload,
            ref_map={handle: ref_map[handle]},
        )


_BLIND_SPOT_CATEGORIES = [
    "authority_confusion",
    "failure_behavior_omission",
    "boundary_lifecycle_ambiguity",
    "feedback_loop_closure",
    "observability_reconciliation_gap",
    "hidden_framework_vendor_lock_in",
    "time_dependent_behavior",
    "human_override_path",
    "p_and_l_ledger_authority_confusion",
    "order_signal_authority_confusion",
    "stream_failure_behavior",
    "feed_gap_reconnect_semantics",
    "session_boundary_behavior",
    "risk_gate_ownership",
    "reconciliation_source_of_truth",
    "execution_state_reporting_feedback_loop",
    "framework_lock_in_masked_as_architecture_choice",
]

_CATEGORY_GAP_TYPES = {
    "authority_confusion": "authority_ownership",
    "authority_ambiguity": "authority_ownership",
    "failure_behavior_omission": "failure_mode",
    "failure_mode_omission": "failure_mode",
    "stream_failure_behavior": "failure_mode",
    "boundary_lifecycle_ambiguity": "scope_boundary",
    "lifecycle_ambiguity": "scope_boundary",
    "session_boundary_behavior": "scope_boundary",
    "feedback_loop_closure": "blind_spot",
    "execution_state_reporting_feedback_loop": "blind_spot",
    "observability_reconciliation_gap": "blind_spot",
    "observability_gap": "blind_spot",
    "reconciliation_source_of_truth": "authority_ownership",
    "time_dependent_behavior": "temporal_assumption",
    "human_override_path": "authority_ownership",
    "hidden_framework_vendor_lock_in": "blind_spot",
    "framework_lock_in_masked_as_architecture_choice": "blind_spot",
    "open_dependency": "dependency_chain",
    "external_validation_needed": "dependency_chain",
    "scope_conflict": "scope_conflict",
    "contradiction": "contradiction",
}


def _finding_category(finding: dict[str, Any]) -> str:
    return finding.get("category") or finding.get("kind") or "blind_spot"


def _work_item_payload(finding: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(proposal)
    related_refs = payload.pop("related_refs", None) or finding.get("refs", [])
    source_refs = payload.pop("source_assumption_refs", None)
    payload["status"] = "open"
    if related_refs:
        payload["target_entity"] = related_refs[0]
    if source_refs is None:
        source_refs = [ref for ref in finding.get("refs", []) if ref.startswith("A-")]
    payload["source_assumption_ids"] = list(source_refs)
    payload.setdefault("gap_type", _CATEGORY_GAP_TYPES.get(_finding_category(finding), "blind_spot"))
    return payload


def _work_key(payload: dict[str, Any]) -> tuple:
    return (
        payload.get("target_entity"),
        payload.get("question", ""),
        payload.get("gap_type"),
    )


def _existing_conversion_keys(ledger: dict[str, Any]) -> dict[str, set[tuple]]:
    return {
        "work_item": {
            _work_key(item)
            for item in ledger.get("work_items", [])
        },
        "risk": {
            (tuple(item.get("source_refs", [])), item.get("statement", ""))
            for item in ledger.get("risks", [])
        },
        "contradiction": {
            (tuple(item.get("refs", [])), item.get("description", ""))
            for item in ledger.get("contradictions", [])
        },
        "assumption": {
            (item.get("statement", ""), tuple(item.get("depends_on", [])))
            for item in ledger.get("assumptions", [])
        },
    }
