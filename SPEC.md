# Governing Build Prompt: Stateful Interrogation Harness (v1, Canonical)

## 0. Status of This Document

This is the complete and authoritative specification for v1. It supersedes all prior drafts. Build to this document. Where this document is silent, the operator MUST choose the simplest implementation consistent with the Invariants in Section 2 and MUST NOT introduce behavior that contradicts them. Do not request scope expansion. Do not add features listed as out of scope.

Normative keywords: MUST, MUST NOT, REJECT, and MAY carry their strict meanings. "REJECT" means: do not mutate ledger state, append a rejection event, and surface the reason.

## 1. Purpose

Build a local, file backed, event sourced harness that converts messy human input into an auditable, implementation grade ground truth record through a disciplined one question at a time interrogation loop. The language model proposes; the harness decides, validates, mints identity, and persists. The model is never the source of truth.

## 2. Invariants (Non Negotiable)

These hold at all times. Any implementation that can violate one of these is incorrect regardless of test results.

1. **External truth.** The append only event log (`events.jsonl`) is the sole authority. The ledger (`ledger.json`) is a pure projection derived by replaying accepted events in order. If the two disagree, the event log wins and the ledger MUST be discarded and rebuilt.
2. **Projection purity.** Rebuilding the ledger from the event log MUST be a deterministic, side effect free fold. It MUST NOT call the model, read a clock, generate identity, or read any state outside the event log. Rebuilding the same `events.jsonl` twice MUST produce byte identical `ledger.json` after canonical serialization (Section 9).
3. **Harness owned identity.** Durable IDs are minted only by the harness, only at the moment a creating event is accepted, and are frozen inside that event's payload. Projection reads IDs from events and never mints. The model emits temporary handles only.
4. **No silent state change.** Every state transition occurs through exactly one appended, validated event. Events are never edited or deleted. Corrections are new events. Revisions preserve prior state in history.
5. **Validate before mutate.** No model output mutates state until it passes the full validation pipeline (Section 8). Malformed output, unknown references, unverifiable provenance, and illegal transitions cannot reach the ledger.
6. **No invented confidence.** Model inferences are never recorded as user confirmed. High blast radius items never disappear silently. Force close never relabels unresolved work as resolved and never promotes provisional assumptions to locked.

## 3. Session Layout

```text
/sessions/{session_id}/source.md          user provided input, written once per add-source
/sessions/{session_id}/events.jsonl        append only, authoritative, one compact JSON object per line
/sessions/{session_id}/ledger.json         derived projection, rebuildable and disposable
/sessions/{session_id}/final_artifact.md   generated from the projection only
```

`session_id` MUST be filesystem safe and stable for the life of the session. `source.md` MAY be appended to by repeated `add-source`; each append is recorded as a `SOURCE_ADDED` event carrying the content hash of the full file after the write.

## 4. Object Model

The model separates entities (the things under audit) from work items (the open interrogation work about those things). An assumption is an entity. The open question that tests an assumption is a work item. There is no third representation and no duplication between the two.

### 4.1 Entities

**Assumption** (`A-NNNN`)
```json
{
  "id": "A-0001",
  "statement": "string",
  "status": "candidate | provisional | locked | rejected | revised | deferred",
  "source_type": "user_stated | model_inferred | external_required",
  "source_excerpt": "string | null",
  "source_excerpt_verified": true,
  "blast_radius": "high | medium | low",
  "downstream_impact": "string",
  "risk_if_wrong": "string",
  "tested_by_work_item": "W-0001 | null",
  "user_answer_events": ["E-0007"],
  "revision_history": [{"event_id": "E-0009", "prior_statement": "string", "new_statement": "string"}],
  "created_event": "E-0001",
  "updated_event": "E-0009"
}
```

**Term** (`T-NNNN`): `id`, `term`, `definition` (nullable), `status` (`undefined | provisional | locked | rejected | revised`), `revision_history`, `created_event`, `updated_event`.

**Decision** (`D-NNNN`): `id`, `decision`, `status` (`needed | provisional | locked | deferred | rejected | revised`), `rationale` (nullable), `revision_history`, `created_event`, `updated_event`.

**Risk** (`R-NNNN`): `id`, `statement`, `severity` (`high | medium | low`), `status` (`open | mitigated | accepted | deferred`), `source_refs[]`, `created_event`, `updated_event`.

**Contradiction** (`C-NNNN`): `id`, `refs[]` (two or more entity IDs), `severity`, `description`, `status` (`open | resolved | deferred`), `resolution_work_item` (nullable), `created_event`, `updated_event`.

### 4.2 Work Item (`W-NNNN`)

A single pool of all open interrogation work. There are no separate arrays for questions, decisions, terms, or risks.

```json
{
  "id": "W-0001",
  "kind": "resolve_assumption | define_term | make_decision | resolve_contradiction | mitigate_risk | validate_external | clarify",
  "status": "open | active | answered | deferred | resolved | blocked",
  "question": "string",
  "why_it_matters": "string",
  "what_breaks_if_wrong": "string",
  "blast_radius": "high | medium | low",
  "blocks_closure": true,
  "target_entity": "A-0001 | T-0001 | D-0001 | R-0001 | C-0001 | null",
  "recommended_default": "string | null",
  "recommended_default_basis": "E-NNNN | A-NNNN | null",
  "answer_options": ["confirm", "reject", "revise", "defer", "unknown"],
  "deferred_reason": "string | null",
  "created_event": "E-0002",
  "updated_event": "E-0008"
}
```

`blocks_closure` MUST be `true` for every `blast_radius: high` work item. At most one work item may hold status `active` at any time; the projection MUST enforce this.

## 5. Blast Radius Rubric

Applied whenever ranking or classifying assumptions, work items, risks, contradiction severity, and decisions.

**High.** A wrong or missing answer can cause silent incorrect behavior, bad implementation architecture, data corruption, capital loss, legal or financial or housing or tax or medical or compliance exposure, security or privacy failure, a downstream builder adopting a materially wrong assumption, irreversible or expensive rework, or false confidence in an invalid specification.

**Medium.** A wrong or missing answer can cause meaningful rework, brittle UX, incorrect prioritization, confusing or incomplete implementation, weak handoff quality, or non critical but material inconsistency.

**Low.** A wrong or missing answer is cosmetic, wording level, preference level, easily reversible, or not structurally material to implementation or governance.

## 6. Event Model

### 6.1 Event Envelope

```json
{
  "event_id": "E-0001",
  "session_id": "string",
  "schema_version": "1.0.0",
  "timestamp": "ISO-8601 UTC",
  "event_type": "string (closed set, Section 6.2)",
  "actor": "user | model | harness",
  "correlation_id": "string (groups all events from one operation)",
  "idempotency_key": "string (Section 7)",
  "payload": {},
  "ref_map": {"tmp_assumption_1": "A-0001"}
}
```

`ref_map` is present only on creating events and records the temporary handle to durable ID mapping decided at acceptance. `event_id` values are minted sequentially by the harness (`E-0001`, `E-0002`, ...) at append time and are never reused. Events are appended one per line in canonical compact form (Section 9).

### 6.2 Closed Event Type Set

No event type outside this set may be appended.

```text
SESSION_CREATED
SOURCE_ADDED
MODEL_RESPONSE_RECORDED        actor=model; records raw output, job name, accepted flag, validation_errors
OPERATION_FAILED               timeout or transport failure; carries retryable flag
PROPOSAL_REJECTED              a model proposal failed semantic validation; carries reason and the rejected proposal
ASSUMPTION_CREATED
TERM_CREATED
DECISION_CREATED
RISK_CREATED
CONTRADICTION_CREATED
WORK_ITEM_CREATED
QUESTION_ASKED                 carries work_item_id and an immutable question snapshot
WORK_ITEM_STATUS_CHANGED       carries from, to, and reason
ASSUMPTION_TRANSITIONED        carries from, to, reason, user_answer_event, and (on revise) prior and new statement
TERM_TRANSITIONED
DECISION_TRANSITIONED
RISK_TRANSITIONED
CONTRADICTION_TRANSITIONED
AUDIT_RUN                      carries the audit findings summary
FORCE_CLOSED
ARTIFACT_GENERATED
```

Every model call MUST produce a `MODEL_RESPONSE_RECORDED` event whether accepted or rejected. Every transport or timeout failure MUST produce an `OPERATION_FAILED` event. Neither mutates entity state.

## 7. Identity and Idempotency

### 7.1 Identity

Creation flows (`initial_extraction`, `interpret_user_answer`, and harness conversion of audit findings) reference new entities by temporary handle only (`tmp_assumption_1`, `tmp_work_1`, `tmp_risk_1`, `tmp_term_1`, `tmp_decision_1`, `tmp_contradiction_1`). On acceptance the harness mints the next durable ID per prefix, writes it into the creating event payload, and records the handle to ID mapping in `ref_map`. Durable IDs are monotonic per prefix per session. The model MUST NOT emit any durable ID in creation output; such output is REJECTED. Model output referencing a durable ID that does not exist in the current projection is REJECTED.

### 7.2 Idempotency

Idempotency is enforced at the operation level. Each operation (one CLI invocation that may append several events under one `correlation_id`) carries one `idempotency_key`, computed as a stable hash of `session_id`, operation name, and the canonical serialization of the operation input (for model jobs, the input projection plus the answer text). The harness maintains a map of seen idempotency keys to their resulting `correlation_id`. Re running an operation with a previously accepted idempotency key MUST be a no op that returns the prior result and appends no new events. A retried operation after a rejected or failed attempt MAY reuse the key and proceed, because no accepted result exists for it.

## 8. Validation Pipeline

Every model response passes these stages in order. Failure at any stage halts the operation for that response, appends the appropriate rejection or failure event, and leaves entity state untouched.

1. **Transport.** On timeout or API error: append `OPERATION_FAILED` (retryable true). Do not mutate. The operation MAY be retried under the same idempotency key.
2. **Parse.** Output MUST be valid JSON. On failure: append `MODEL_RESPONSE_RECORDED` (accepted false), then retry exactly once with a repair prompt that includes the parse error. A second parse failure halts the operation and surfaces the error.
3. **Schema.** Output MUST match the job's output schema exactly: required fields present, enum values legal, no durable IDs in creation fields. On failure: append `MODEL_RESPONSE_RECORDED` (accepted false) with the schema errors, retry exactly once with the errors included, then halt on second failure.
4. **Semantic.** References to durable IDs MUST resolve in the current projection. Proposed entity transitions MUST be legal under Section 10. For `source_type: user_stated`, the `source_excerpt` MUST verify per Section 11. A `recommended_default` that is non null MUST carry a `recommended_default_basis` that resolves in the projection. On any semantic failure: append `PROPOSAL_REJECTED` with the specific reason. Do not mutate. Do not silently repair.
5. **Apply.** Mint IDs for accepted creations, append the creating and transition events under one `correlation_id`, then rebuild the projection.

A response that partially fails MUST NOT partially apply. Either all accepted events for the operation are appended or none are.

## 9. Canonical Serialization

`ledger.json`: UTF-8, LF line endings, two space indent, object keys sorted lexicographically at every level, entity arrays sorted by `id` ascending, a single trailing newline, no trailing whitespace. `events.jsonl`: UTF-8, LF, one event per line as compact JSON (no spaces after separators) with keys sorted lexicographically. These rules exist so the log and ledger are Git diffable and so rebuild is byte stable. The harness MUST serialize through one shared canonical function used by both writing and rebuild.

## 10. State Machines

The harness MUST enforce these transitions. Any proposed transition outside the allowed set is illegal and triggers `PROPOSAL_REJECTED` with no mutation. A new question MUST NOT be asked while an illegal transition for the active work item remains unresolved or undiscarded.

### Assumption
```text
Allowed:
candidate   -> provisional | locked | rejected | deferred
provisional -> locked | rejected | revised | deferred
locked      -> revised | deferred
revised     -> provisional | locked | rejected | deferred
deferred    -> provisional | locked | rejected | revised
rejected    -> revised
Forbidden (explicit): rejected -> locked, rejected -> provisional, locked -> rejected
```
A rejected assumption re enters only through `revised`, preserving the rejected record. A locked assumption changes only through `revised`; it is never silently overwritten.

### Work Item
```text
open      -> active | deferred | blocked
active    -> answered | deferred | blocked
answered  -> resolved | open
deferred  -> open | blocked
blocked   -> open | deferred
resolved  -> open
```
Reopening a resolved work item requires an event whose reason explains why it became unresolved.

### Risk
```text
open      -> mitigated | accepted | deferred
mitigated -> open
accepted  -> open
deferred  -> open
```

### Contradiction
```text
open     -> resolved | deferred
resolved -> open
deferred -> open
```

### Term
```text
undefined   -> provisional | locked | rejected
provisional -> locked | revised | rejected
locked      -> revised
revised     -> provisional | locked | rejected
rejected    -> revised
```

### Decision
```text
needed      -> provisional | locked | deferred | rejected
provisional -> locked | revised | deferred
locked      -> revised
revised     -> provisional | locked | rejected
deferred    -> provisional | locked | rejected
rejected    -> revised
```

## 11. Provenance Verification

For `source_type: user_stated`, the harness verifies `source_excerpt` against `source.md` using normalized matching: collapse every run of whitespace to a single space and trim both the excerpt and the source, then test for a case sensitive substring match. On success, set `source_excerpt_verified: true`. On failure, the harness MUST NOT accept the user_stated claim and MUST NOT discard the candidate: it downgrades the entity to `source_type: model_inferred` with `source_excerpt_verified: false`, recording the downgrade reason in the creating event. A `model_inferred` assumption remains unconfirmed and can be locked only after an explicit user answer that supports the lock. An `external_required` assumption MUST NOT be locked as fact without external validation or explicit user acceptance recorded as an answer.

## 12. Model Jobs

Five jobs, each with its own schema, validator, retry behavior, and permissions. No generic catch all call. Jobs MUST NOT exceed their stated permissions.

Permission summary: `initial_extraction` and `interpret_user_answer` MAY create entities (by temp handle). `rank_next_work_item` selects only. `contradiction_audit` reports findings only; the harness converts them. `artifact_generation` reads only.

### Job 1: initial_extraction
Inspects `source.md`; proposes candidate assumptions, work items, risks, terms, decisions, contradictions. Input carries `session_id`, `schema_version`, `source_markdown`, and instruction flags (`do_not_mint_durable_ids`, `mark_model_inferences`, `cite_source_excerpts`, all true). Output uses temp handles, carries `source_type`, `source_excerpt`, `blast_radius`, `downstream_impact`, `risk_if_wrong` for assumptions, and `kind`, `question`, `why_it_matters`, `what_breaks_if_wrong`, `blast_radius`, `blocks_closure`, `related_temp_refs` for work items. Validation per Section 8, plus: every `blast_radius: high` work item MUST have `blocks_closure: true`; `external_required` is accepted only when the missing external fact is named.

### Job 2: rank_next_work_item
Selects the single highest value unresolved work item from the projection under policy (`prefer_high_blast_radius`, `prefer_closure_blockers`, `one_question_at_a_time`). Output: one `selected_work_item_id` that MUST exist and be unresolved, the question fields, the tested entity ID, `recommended_default` (null unless a projection ref justifies it, in which case `recommended_default_basis` is required), and `allowed_answers`. This job MUST NOT create work items or any other entity.

### Job 3: interpret_user_answer
Converts the user answer to the active work item into proposed transition or creation events. Input carries the projection, the active work item, and the raw `user_answer`. Output: `proposed_events[]` (each an event_type from the closed set with target ref or temp handle and payload), `followup_required` boolean, `warnings[]`. Validation per Section 8, plus: the model MUST NOT propose locking an assumption unless the answer clearly supports it; ambiguous answers MUST yield `followup_required: true` or defer or open risk events rather than a lock; `unknown` and `defer` MUST NOT stall and MUST route to a deferred work item, an open risk, or an external validation work item.

### Job 4: contradiction_audit
Reads `source_markdown` and the projection; reports contradictions, missing provenance, invalid source excerpts, unresolved high blast radius items, and artifact blockers. All refs MUST resolve. This job mutates nothing. The harness records `AUDIT_RUN`, then deterministically converts findings into events: a new contradiction becomes `CONTRADICTION_CREATED` plus a `resolve_contradiction` work item (`blocks_closure` set by severity); an invalid excerpt found here becomes an assumption provenance downgrade plus a `validate_external` or `resolve_assumption` work item; an unresolved high blast radius finding ensures the corresponding work item has `blocks_closure: true`.

### Job 5: artifact_generation
Generates the final artifact from the projection only, in `closure_mode: force_close`. Output: `artifact_markdown`, `blocking_warnings[]`, `open_risk_register[]`, `traceability_summary[]`. The artifact MUST NOT invent locked assumptions, MUST NOT omit unresolved high blast radius work, MUST include the open risk register, MUST include provenance for every locked assumption, and MUST separate facts, assumptions, decisions, unresolved risks, and external validation needs. If the model detects a missing high blast radius premise during generation, it MUST emit a blocking warning rather than fill the gap.

## 13. Answer Handling

Supported answer classes: `confirm`, `reject`, `revise`, `defer`, `unknown`, and freeform clarification. `confirm` may lock or reinforce only when the active question maps cleanly to one entity. `reject` may reject a candidate or provisional assumption only via a legal transition. `revise` MUST preserve the prior statement in `revision_history`. `defer` keeps the item unresolved and records a reason when provided. `unknown` MUST create or update an open risk, a deferred work item, or an external validation work item, and MUST NOT stall. Freeform clarification is interpreted by the model and validated before any mutation. The harness MUST NEVER force an answer when the user says unknown or defer.

## 14. Closure

V1 supports force close only. There is no automatic sufficiency closure. `generate-artifact` is permitted only when either no unresolved `blocks_closure` work items remain, or a `FORCE_CLOSED` event already exists for the session. Force close MUST run `contradiction_audit` first, MUST record a `FORCE_CLOSED` event, MUST NOT relabel unresolved items as resolved, and MUST NOT promote provisional assumptions to locked. When force closed with unresolved high blast radius work, the artifact MUST surface every such item prominently in the open risk register.

## 15. Error and Retry Behavior

Malformed JSON and schema failures: record the rejected response, retry once with the error in a repair prompt, halt on second failure with no mutation. Illegal transitions: record `PROPOSAL_REJECTED`, do not mutate, surface the reason, and do not ask a new question until the proposal is resolved or discarded. Timeout or transport failure: record `OPERATION_FAILED`, do not mutate, allow retry under the same idempotency key. Idempotency: re running an accepted operation creates no new durable records and no new events.

## 16. Components

Implement with clear boundaries and no leakage of model reasoning into the harness.

`SessionStore` (directories, read and write of source, append events, read events, write rebuilt ledger, write artifact, export). `EventLog` (append only enforcement, sequential `event_id` minting, idempotency key map, preservation of rejected and failed events). `LedgerProjector` (pure fold over accepted events into the projection; never mints, never calls the model, never reads a clock). `StateMachine` (legal transition tables and explicit illegal transition errors). `IdAllocator` (durable ID minting at acceptance, temp handle mapping, collision and duplication prevention). `ModelAdapter` (isolated model calls, swappable, supports the deterministic mock, returns raw output, mutates nothing). `ModelContractValidator` (the full pipeline of Section 8). `InterrogationEngine` (ask next, one active question, route answers, keep unknown and defer moving). `AuditEngine` (run audit, validate findings, convert to events deterministically). `ArtifactGenerator` (artifact from projection, no invention, open risk register on force close).

## 17. Deterministic Mock Model

V1 MUST ship a scripted mock model that drives the entire acceptance suite with no live API. It MUST provide canned, deterministic responses for: initial extraction, ranking, interpreting each of confirm, reject, revise, defer, and unknown, contradiction audit, artifact generation, a malformed JSON response, and an illegal transition proposal. The mock is the default model for tests.

## 18. Commands (CLI)

```text
create-session          new directory; append SESSION_CREATED
add-source              write source.md; append SOURCE_ADDED with content hash
run-initial-extraction  run job 1; validate; mint IDs; append creation events; rebuild ledger
show-ledger             print current projection
show-open-work          print unresolved work items sorted by blast radius then closure impact
ask-next                run job 2; mark one work item active; append QUESTION_ASKED; print one question
answer                  accept user answer for the active item; run job 3; validate; apply; rebuild
defer                   mark active or named work item deferred with optional reason
revise                  append a revision transition for an assumption, term, or decision
run-audit               run job 4; record AUDIT_RUN; convert findings to events
force-close             run audit; append FORCE_CLOSED; enable artifact generation with open risk register
generate-artifact       run job 5 from projection; write final_artifact.md; append ARTIFACT_GENERATED
rebuild-ledger          delete and rebuild ledger.json from events.jsonl
export-session          export source, event log, ledger, and artifact
resume-session          load an existing session and verify the ledger rebuilds byte identically
```

## 19. Final Artifact

Generated from the projection only, with these sections in order: Source Summary, Locked Assumptions, Provisional Assumptions, Rejected Assumptions, Revised Assumptions, Locked Decisions, Defined Terms, Open Work Items, Open Risk Register, Contradictions and Resolutions, External Validation Required, Implementation Constraints, Downstream Builder Instructions, Provenance Index, Closure Mode, Known Limits. Locked assumptions MUST carry traceability (source type, verified excerpt where user stated, testing question, user answer event, revision history). Open high blast radius items and external validation needs MUST be visible and unburied. Provisional and model inferred assumptions MUST NOT be presented as facts or as user confirmed. The artifact MUST be usable by a downstream builder without inferring hidden logic.

## 20. Acceptance Tests

The build passes only when all of these pass against the deterministic mock model, with no live API.

1. Create a session; `SESSION_CREATED` recorded.
2. Add messy source; `source.md` written; `SOURCE_ADDED` carries the correct content hash.
3. Run initial extraction; accepted creation events appended; ledger rebuilt.
4. `events.jsonl` exists, is append only, and contains the expected accepted events.
5. `ledger.json` is reconstructed solely from events.
6. Temp handles map to harness minted durable IDs via `ref_map`.
7. Model output containing a durable ID in creation fields is rejected.
8. A user_stated excerpt is verified against `source.md`.
9. A user_stated excerpt absent from source is downgraded to model_inferred with `source_excerpt_verified: false`, and the candidate is not dropped.
10. Exactly one work item is active after `ask-next`.
11. A `confirm` legally locks a provisional assumption.
12. A direct `rejected -> locked` proposal is refused as illegal with no mutation.
13. A locked assumption cannot be overwritten except through `revised`.
14. A revision preserves the prior statement in `revision_history`.
15. `unknown` creates or updates an open risk, deferred work item, or external validation work item, and does not stall.
16. `defer` does not stall the loop.
17. Malformed JSON does not mutate the ledger and is recorded.
18. An illegal transition is recorded as `PROPOSAL_REJECTED` and does not mutate the ledger.
19. Re running an operation under the same idempotency key creates no duplicate records and no new events.
20. `ledger.json` can be deleted and rebuilt byte identically; rebuilding twice yields identical bytes.
21. Contradiction audit records `AUDIT_RUN` and converts findings into events deterministically.
22. Force close preserves unresolved high blast radius items in the open risk register and does not relabel them.
23. The final artifact includes locked assumptions, open risks, provenance, and downstream builder instructions.
24. The final artifact invents no locked assumption absent from the projection.
25. `resume-session` loads an existing session and verifies a byte identical rebuild.

## 21. Out of Scope (Do Not Implement)

Full multi stage orchestration; multi model routing; complex UI; cloud deployment; authentication; team or real time collaboration; database backed storage; automated web research; domain specific blind spot packs; automatic sufficiency closure; background jobs; any prompt only mode that substitutes for the harness.

## 22. Implementation Constraints

TypeScript or Python. Local file backed storage only. Prefer simple, inspectable code over framework complexity; introduce no agent or orchestration framework. The ledger and event log MUST be human readable and Git diffable. The `ModelAdapter` MUST be swappable. The full acceptance suite MUST pass with the mock model before any live model is used. The acceptance suite MUST be runnable through a single documented command stated in the README (for Python, pytest), and that command MUST run the full suite offline against the deterministic mock model with no live API. Do not use em dashes in any generated artifact, README, or code comment; use commas, periods, parentheses, or colons.

## 23. Completion Gate

The build is complete if and only if all 25 acceptance tests pass against the deterministic mock model and the delivered sample session demonstrates the full event sourced loop end to end. No other criterion stands in for this gate.

## 24. Delivery Package

```text
README.md
/src
/tests
/sessions/sample_session/source.md
/sessions/sample_session/events.jsonl
/sessions/sample_session/ledger.json
/sessions/sample_session/final_artifact.md
```

The sample session MUST demonstrate: at least three candidate assumptions; at least one model_inferred assumption; at least one user_stated assumption with a verified excerpt; at least one high blast radius work item; one unknown answer routed to an open risk; one deferred item; one revised assumption; one rejected illegal transition; and one force closed final artifact. Stop only when the harness runs locally, all tests pass against the mock model, and the sample session proves the event sourced interrogation loop end to end.