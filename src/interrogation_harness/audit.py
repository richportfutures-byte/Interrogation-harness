"""Audit engine and deterministic conversion of audit findings."""

from __future__ import annotations

from typing import Any

from interrogation_harness.events import Actor, EventType
from interrogation_harness.ids import IdAllocator
from interrogation_harness.model.adapter import ModelJob


class AuditEngine:
    """Run contradiction audit through validation, then convert findings."""

    def __init__(self, operations) -> None:
        self.ops = operations

    def run_audit(self, *, operation_name: str = "run-audit") -> dict[str, Any]:
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
        self._convert_findings(result.parsed_output, ids)
        return {"accepted": True, "ledger": self.ops.rebuild_ledger(), "findings": result.parsed_output}

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

    def _convert_findings(self, parsed: dict[str, Any], ids) -> None:
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
