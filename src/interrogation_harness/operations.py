"""High level file-backed operations for the Section 18 commands."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from interrogation_harness import canonical
from interrogation_harness.audit import AuditEngine
from interrogation_harness.event_log import EventLog
from interrogation_harness.events import Actor, EventType
from interrogation_harness.interrogation import InterrogationEngine, OperationError
from interrogation_harness.model import DEFAULT_MODEL_ADAPTER
from interrogation_harness.model.adapter import ModelAdapter, ModelJob
from interrogation_harness.projection import LedgerProjector
from interrogation_harness.session_store import SessionStore
from interrogation_harness.validation import ModelContractValidator, ModelValidationResult


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for event envelopes."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def content_hash(text: str) -> str:
    """Return the SHA-256 hex digest for text written as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperationIds:
    """The operation-level IDs attached to all events in one command."""

    correlation_id: str
    idempotency_key: str
    timestamp: str


class HarnessOperations:
    """Convenience facade used by tests and the CLI."""

    def __init__(
        self,
        root: str | Path,
        session_id: str,
        *,
        model: ModelAdapter = DEFAULT_MODEL_ADAPTER,
        now: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.store = SessionStore(root, session_id)
        self.session_id = session_id
        self.model = model
        self.now = now
        self.event_log = EventLog(self.store)
        self.projector = LedgerProjector()

    # -- shared helpers ----------------------------------------------------

    def op_ids(self, operation: str, data: dict[str, Any] | None = None) -> OperationIds:
        payload = {"session_id": self.session_id, "operation": operation, "input": data or {}}
        digest = hashlib.sha256(canonical.dumps_event_line(payload).encode("utf-8")).hexdigest()
        next_event = self.event_log.next_event_id().lower()
        return OperationIds(
            correlation_id=f"{operation}-{next_event}",
            idempotency_key=f"{operation}-{digest}",
            timestamp=self.now(),
        )

    def validator(self) -> ModelContractValidator:
        return ModelContractValidator(self.event_log, self.model, self.projector)

    def ledger(self) -> dict[str, Any]:
        return self.projector.project(self.event_log.read_events())

    def rebuild_ledger(self) -> dict[str, Any]:
        self.store.delete_ledger()
        ledger = self.ledger()
        self.store.write_ledger(ledger)
        return ledger

    # -- lifecycle ---------------------------------------------------------

    def create_session(
        self,
        *,
        protocol_version: str | None = None,
        session_frame: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a session.

        Default (V1) behavior is unchanged: the SESSION_CREATED payload is exactly
        {"session_id": ...} and the idempotency input is empty, so V1 bytes are
        preserved. protocol_version and session_frame are written only when supplied
        (V2 activation, V2 Implementation Spec Section 1 and Decision D1).
        """
        self.store.create()
        op_input: dict[str, Any] = {}
        payload: dict[str, Any] = {"session_id": self.session_id}
        if protocol_version is not None:
            op_input["protocol_version"] = protocol_version
            payload["protocol_version"] = protocol_version
        if session_frame is not None:
            op_input["session_frame"] = session_frame
            payload["session_frame"] = session_frame
        ids = self.op_ids("create-session", op_input)
        if self.event_log.accepted_correlation(ids.idempotency_key) is None:
            self.event_log.append(
                event_type=EventType.SESSION_CREATED,
                actor=Actor.HARNESS,
                session_id=self.session_id,
                correlation_id=ids.correlation_id,
                idempotency_key=ids.idempotency_key,
                timestamp=ids.timestamp,
                payload=payload,
            )
        return self.rebuild_ledger()

    def add_source(self, content: str) -> dict[str, Any]:
        self.store.create()
        prior = self.store.read_source() if self.store.source_exists() else ""
        ids = self.op_ids("add-source", {"content": content, "prior_hash": content_hash(prior)})
        if self.event_log.accepted_correlation(ids.idempotency_key) is not None:
            return self.rebuild_ledger()
        if self.store.source_exists():
            self.store.append_source(content)
        else:
            self.store.write_source(content)
        full_source = self.store.read_source()
        self.event_log.append(
            event_type=EventType.SOURCE_ADDED,
            actor=Actor.USER,
            session_id=self.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            payload={"content_hash": content_hash(full_source)},
        )
        return self.rebuild_ledger()

    # -- model-backed commands -------------------------------------------

    def protocol_version(self) -> str:
        """Project the current protocol version (defaults to V1)."""
        return self.ledger().get("protocol_version", "1.0.0")

    def run_initial_extraction(self) -> ModelValidationResult:
        # V2 sessions alias run-initial-extraction to run-intake (V2 spec Section 7).
        if self.protocol_version() == "2.0.0":
            return self.run_intake()
        source_markdown = self.store.read_source()
        payload = {
            "session_id": self.session_id,
            "schema_version": "1.0.0",
            "source_markdown": source_markdown,
            "do_not_mint_durable_ids": True,
            "mark_model_inferences": True,
            "cite_source_excerpts": True,
        }
        ids = self.op_ids("run-initial-extraction", payload)
        return self.validator().run(
            ModelJob.INITIAL_EXTRACTION,
            session_id=self.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload=payload,
            source_markdown=source_markdown,
        )

    def run_intake(self, *, upgrade_to_v2: bool = False) -> ModelValidationResult:
        """Run the V2 intake job.

        A V1 session is upgraded only with an explicit ``--upgrade-to-v2`` request; this
        is the sole path that turns a V1 session into a V2 session (V2 spec Section 6).
        """
        is_v2 = self.protocol_version() == "2.0.0"
        if not is_v2 and not upgrade_to_v2:
            raise OperationError(
                "session is V1; pass --upgrade-to-v2 to run V2 intake on it"
            )
        source_markdown = self.store.read_source() if self.store.source_exists() else ""
        payload = {
            "session_id": self.session_id,
            "schema_version": "1.0.0",
            "source_markdown": source_markdown,
            "do_not_mint_durable_ids": True,
            "mark_model_inferences": True,
            "cite_source_excerpts": True,
        }
        ids = self.op_ids("run-intake", payload)
        return self.validator().run(
            ModelJob.INTAKE_UNSTRUCTURED_INPUT,
            session_id=self.session_id,
            correlation_id=ids.correlation_id,
            idempotency_key=ids.idempotency_key,
            timestamp=ids.timestamp,
            request_payload=payload,
            source_markdown=source_markdown,
        )

    def ask_next(self) -> dict[str, Any]:
        return InterrogationEngine(self).ask_next()

    def answer(self, answer_text: str, *, answer_class: str | None = None) -> ModelValidationResult:
        return InterrogationEngine(self).answer(answer_text, answer_class=answer_class)

    def defer(self, work_item_id: str | None = None, reason: str = "deferred") -> dict[str, Any]:
        return InterrogationEngine(self).defer(work_item_id=work_item_id, reason=reason)

    def revise(self, entity_id: str, new_statement: str, reason: str = "user revised") -> dict[str, Any]:
        return InterrogationEngine(self).revise(entity_id, new_statement, reason=reason)

    def run_audit(self, *, operation_name: str = "run-audit") -> dict[str, Any]:
        return AuditEngine(self).run_audit(operation_name=operation_name)

    def run_blind_spot_audit(self) -> dict[str, Any]:
        return AuditEngine(self).run_blind_spot_audit()

    def force_close(self, reason: str = "force close requested") -> dict[str, Any]:
        return AuditEngine(self).force_close(reason=reason)

    def generate_artifact(self) -> dict[str, Any]:
        from interrogation_harness.artifact import ArtifactGenerator

        return ArtifactGenerator(self).generate_artifact()

    # -- read/export commands --------------------------------------------

    def show_ledger(self) -> dict[str, Any]:
        ledger = self.ledger()
        self.store.write_ledger(ledger)
        return ledger

    def show_open_work(self) -> list[dict[str, Any]]:
        work = [
            item
            for item in self.ledger().get("work_items", [])
            if item.get("status") != "resolved"
        ]
        priority = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            work,
            key=lambda item: (
                priority.get(item.get("blast_radius"), 9),
                not bool(item.get("blocks_closure")),
                item.get("id", ""),
            ),
        )

    def export_session(self, dest: str | Path) -> list[Path]:
        return self.store.export(dest)

    def resume_session(self) -> bool:
        rebuilt_text = canonical.dumps_ledger(self.ledger())
        if self.store.ledger_exists():
            prior = self.store.ledger_path.read_text(encoding="utf-8")
            identical = prior == rebuilt_text
        else:
            identical = True
        self.store.write_ledger(canonical.loads(rebuilt_text))
        return identical
