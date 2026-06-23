"""Interrogation engine: ask next, answer, defer, and revise."""

from __future__ import annotations

from typing import Any

from interrogation_harness.events import Actor, EventType
from interrogation_harness.model.adapter import ModelJob
from interrogation_harness.records import AnswerClass
from interrogation_harness.state_machine import StateMachine


class OperationError(Exception):
    """Raised when an operation cannot be applied to the current projection."""


class InterrogationEngine:
    """One-question-at-a-time workflow over validated model jobs."""

    def __init__(self, operations) -> None:
        self.ops = operations

    def ask_next(self) -> dict[str, Any]:
        ledger = self.ops.ledger()
        # V2 only: refuse to ask while intake is still required (V2 spec Section 6.1).
        if (
            ledger.get("protocol_version") == "2.0.0"
            and ledger.get("intake_status") == "required"
        ):
            raise OperationError(
                "intake required for this V2 session: run `run-intake` before ask-next"
            )
        payload = {
            "session_id": self.ops.session_id,
            "projection": ledger,
            "policy": [
                "prefer_high_blast_radius",
                "prefer_closure_blockers",
                "one_question_at_a_time",
            ],
        }
        ids = self.ops.op_ids("ask-next", payload)
        result = self.ops.validator().run(
            ModelJob.RANK_NEXT_WORK_ITEM,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload=payload,
        )
        if not result.accepted or result.parsed_output is None:
            raise OperationError("; ".join(result.errors) or "rank_next_work_item rejected")

        ledger = self.ops.ledger()
        selected_id = result.parsed_output["selected_work_item_id"]
        selected = _find_by_id(ledger["work_items"], selected_id)
        active = [item for item in ledger["work_items"] if item.get("status") == "active"]
        if active and active[0]["id"] != selected_id:
            raise OperationError(f"another work item is already active: {active[0]['id']}")

        if selected["status"] != "active":
            self._move_work_to_open_if_needed(selected, ids)
            selected = _find_by_id(self.ops.ledger()["work_items"], selected_id)
            self._append_status_change(
                selected,
                "active",
                "selected by rank_next_work_item",
                ids,
            )

        snapshot = {
            "question": result.parsed_output["question"],
            "why_it_matters": result.parsed_output["why_it_matters"],
            "what_breaks_if_wrong": result.parsed_output["what_breaks_if_wrong"],
            "recommended_default": result.parsed_output["recommended_default"],
            "recommended_default_basis": result.parsed_output["recommended_default_basis"],
            "answer_options": result.parsed_output["allowed_answers"],
        }
        self.ops.event_log.append(
            event_type=EventType.QUESTION_ASKED,
            actor=Actor.HARNESS,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            payload={"work_item_id": selected_id, "question_snapshot": snapshot},
        )
        ledger = self.ops.rebuild_ledger()
        active = [item for item in ledger["work_items"] if item.get("status") == "active"]
        if len(active) != 1:
            raise OperationError("ask-next did not leave exactly one active work item")
        return active[0]

    def answer(self, answer_text: str, *, answer_class: str | None = None):
        ledger = self.ops.ledger()
        active = [item for item in ledger["work_items"] if item.get("status") == "active"]
        if len(active) != 1:
            raise OperationError("answer requires exactly one active work item")
        resolved_answer = answer_class or _classify_answer(answer_text)
        payload = {
            "session_id": self.ops.session_id,
            "projection": ledger,
            "active_work_item": active[0],
            "user_answer": answer_text,
            "answer_class": resolved_answer,
        }
        ids = self.ops.op_ids("answer", payload)
        result = self.ops.validator().run(
            ModelJob.INTERPRET_USER_ANSWER,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload=payload,
            source_markdown=(
                answer_text
                if ledger.get("protocol_version") == "2.0.0"
                else self.ops.store.read_source() if self.ops.store.source_exists() else ""
            ),
        )
        if result.accepted:
            self._resolve_answered_work_items(ids)
        return result

    def defer(self, work_item_id: str | None = None, reason: str = "deferred") -> dict[str, Any]:
        ledger = self.ops.ledger()
        if work_item_id is None:
            active = [item for item in ledger["work_items"] if item.get("status") == "active"]
            if len(active) != 1:
                raise OperationError("defer requires one active work item or an explicit id")
            work_item = active[0]
        else:
            work_item = _find_by_id(ledger["work_items"], work_item_id)
        ids = self.ops.op_ids("defer", {"work_item_id": work_item["id"], "reason": reason})
        self._append_status_change(work_item, "deferred", reason, ids, deferred_reason=reason)
        ledger = self.ops.rebuild_ledger()
        return _find_by_id(ledger["work_items"], work_item["id"])

    def revise(self, entity_id: str, new_statement: str, reason: str = "user revised") -> dict[str, Any]:
        ledger = self.ops.ledger()
        collection, entity_type, event_type, text_field = _revision_target(ledger, entity_id)
        entity = _find_by_id(collection, entity_id)
        StateMachine.check(entity_type, entity["status"], "revised")
        ids = self.ops.op_ids(
            "revise",
            {"entity_id": entity_id, "new_statement": new_statement, "reason": reason},
        )
        self.ops.event_log.append(
            event_type=event_type,
            actor=Actor.HARNESS,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            payload={
                "id": entity_id,
                "from": entity["status"],
                "to": "revised",
                "reason": reason,
                "prior_statement": entity.get(text_field) or "",
                "new_statement": new_statement,
            },
        )
        ledger = self.ops.rebuild_ledger()
        return _find_entity(ledger, entity_id)

    def _move_work_to_open_if_needed(self, work_item: dict[str, Any], ids) -> None:
        status = work_item["status"]
        if status == "open":
            return
        if status == "deferred":
            self._append_status_change(work_item, "open", "reopened for ask-next", ids)
            return
        if status == "blocked":
            self._append_status_change(work_item, "open", "unblocked for ask-next", ids)
            return
        if status == "answered":
            self._append_status_change(work_item, "open", "reopened for ask-next", ids)
            return
        raise OperationError(f"cannot activate work item from status {status!r}")

    def _append_status_change(
        self,
        work_item: dict[str, Any],
        to_status: str,
        reason: str,
        ids,
        *,
        deferred_reason: str | None = None,
    ) -> None:
        StateMachine.check("work_item", work_item["status"], to_status)
        payload = {
            "id": work_item["id"],
            "from": work_item["status"],
            "to": to_status,
            "reason": reason,
        }
        if deferred_reason is not None:
            payload["deferred_reason"] = deferred_reason
        self.ops.event_log.append(
            event_type=EventType.WORK_ITEM_STATUS_CHANGED,
            actor=Actor.HARNESS,
            session_id=self.ops.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            payload=payload,
        )
        self.ops.rebuild_ledger()

    def _resolve_answered_work_items(self, ids) -> None:
        ledger = self.ops.ledger()
        for work_item in ledger["work_items"]:
            if work_item.get("status") == "answered":
                self._append_status_change(
                    work_item,
                    "resolved",
                    "answer accepted with no follow-up required",
                    ids,
                )


def _classify_answer(answer_text: str) -> str:
    value = answer_text.strip().lower()
    allowed = {item.value for item in AnswerClass}
    return value if value in allowed else value


def _find_by_id(items: list[dict[str, Any]], entity_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == entity_id:
            return item
    raise OperationError(f"unknown id: {entity_id}")


def _find_entity(ledger: dict[str, Any], entity_id: str) -> dict[str, Any]:
    for key in ("assumptions", "terms", "decisions", "risks", "contradictions", "work_items"):
        try:
            return _find_by_id(ledger[key], entity_id)
        except OperationError:
            pass
    raise OperationError(f"unknown id: {entity_id}")


def _revision_target(ledger: dict[str, Any], entity_id: str):
    if entity_id.startswith("A-"):
        return ledger["assumptions"], "assumption", EventType.ASSUMPTION_TRANSITIONED, "statement"
    if entity_id.startswith("T-"):
        return ledger["terms"], "term", EventType.TERM_TRANSITIONED, "definition"
    if entity_id.startswith("D-"):
        return ledger["decisions"], "decision", EventType.DECISION_TRANSITIONED, "decision"
    raise OperationError("revise supports assumptions, terms, and decisions")
