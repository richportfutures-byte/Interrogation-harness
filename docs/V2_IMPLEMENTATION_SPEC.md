# V2 Implementation Spec: Premise Control Layer (Revised, Canonical)

## 0. Scope

V2 extends the existing V1 event-sourced harness. It must preserve the V1 event log, ledger projection, state machines, validation pipeline, CLI discipline, artifact generation discipline, harness-owned identity, and force-close semantics.

Do not replace the harness. Do not introduce a parallel premise state system. Do not monkey patch the mock. Do not add runtime dependencies unless handwritten validation is proven insufficient.

The model remains untrusted. The harness validates, mints IDs, applies legal transitions, and persists events.

This revision supersedes the earlier draft. Where this document and the earlier draft disagree, this document wins. Where this document is silent, follow SPEC.md (V1) and the Section 0 rule: choose the simplest implementation consistent with the invariants, and do not weaken any invariant.

This document is grounded in the current code. Specific code references that drove the revision:
- `MODEL_RESPONSE_RECORDED.payload` currently stores `{job, raw_output, accepted, validation_errors}` only (`src/interrogation_harness/validation.py`). The parsed model output is not stored, and the projector treats the event as a no-op.
- `AUDIT_RUN.payload` currently stores `{"findings_summary": ...}` with no `audit_type` (`src/interrogation_harness/validation.py`).
- `SESSION_CREATED.payload` currently stores `{"session_id": ...}` only (`src/interrogation_harness/operations.py`).
- The projector emits exactly the dataclass fields of each record via `asdict` (`src/interrogation_harness/projection.py`), so any field added to a record appears in every ledger.
- The committed V1 sample at `sessions/sample_session/` is frozen and is part of the V1 acceptance gate.

## 0.1 Revision Log (changes from the earlier draft)

These are the concrete corrections this revision makes. Each is a binding decision.

1. **session_frame provenance is decided, not conditional.** The earlier draft left an open conditional about parsing raw model output during rebuild. Projection MUST NOT parse `raw_output`. See Decision D1 and the rewritten Section 2.2.
2. **`AUDIT_RUN` gains a structured `audit_type`.** V2 blind-spot audits set `audit_type: "blind_spot"`. V1 audits are left unchanged (absent `audit_type` is interpreted as `"contradiction"`), which keeps the committed V1 sample byte-identical. See Decision D2.
3. **All V2 fields are omit-if-null, and the four V2 ledger-level fields appear only for V2 sessions.** A V1 session produces byte-identical `ledger.json` and `events.jsonl` exactly as today. See Decision D3 and Section 2.5.
4. **The "premise blocker" predicate used by ranking and ask-next is defined concretely** in terms of `blocks_closure`, and the gap categories are enforced at creation time to set `blocks_closure` or a `blocking_reason`. See Decision D4 and Section 6.
5. **Mock policy is tightened.** V2 scenarios are static named entries with explicit raw JSON. The existing dynamic `interpret confirm` helper MUST NOT be extended for V2. See Section 8.

## 0.2 Locked Decisions

**D1. session_frame and protocol_version provenance.**
Projection reads only structured, harness-written event fields. It never parses `raw_output`.
- A V2 session created with `--protocol-version 2.0.0` records `SESSION_CREATED.payload.protocol_version = "2.0.0"` and, when an objective is supplied at creation, `SESSION_CREATED.payload.session_frame`.
- For the upgrade path (`run-intake --upgrade-to-v2` on an existing V1 session), `SESSION_CREATED` already exists and is immutable. When the intake response is accepted, the harness stores the validated `session_frame` as a structured field on that accepted intake event: `MODEL_RESPONSE_RECORDED.payload.session_frame`. This is harness-written validated data, not raw text, so the projector reads it without parsing untrusted output.
- Precedence in projection: `SESSION_CREATED.payload.session_frame` wins; otherwise the validated `session_frame` from the first accepted intake `MODEL_RESPONSE_RECORDED`.

**D2. AUDIT_RUN audit_type.**
V2 blind-spot audits write `AUDIT_RUN.payload.audit_type = "blind_spot"`. V1 contradiction audits are unchanged and may omit `audit_type`; absent `audit_type` is interpreted as `"contradiction"`. Projection treats only `audit_type == "blind_spot"` as a V2 signal and as blind-spot completion.

**D3. Omit-if-null and conditional ledger shape.**
- Entity-level V2 fields default to null or empty and are omitted from the projected entity object when null or empty. V1 entities therefore serialize exactly as today.
- The four V2 ledger-level fields (`protocol_version`, `session_frame`, `intake_status`, `blind_spot_audit_status`) are emitted only when the session is V2 (Section 2.5). For a V1 session the ledger keeps its current V1 shape, byte for byte.

**D4. Premise blocker predicate.**
A work item is a premise blocker iff it is unresolved (status not `resolved`) and `blocks_closure == true`. In V2, every `blast_radius == "high"` work item has `blocks_closure == true`, and a `medium` work item has `blocks_closure == true` only when a `blocking_reason` is present. The gap categories in Section 6.2 are enforced at creation time (by intake and by audit conversion) to set `blocks_closure` or a `blocking_reason`, so ranking and ask-next key on the single concrete signal `blocks_closure`.

## 1. V1/V2 Compatibility and Session Activation

V1 behavior remains valid.

- Existing V1 sessions continue using `initial_extraction` and `contradiction_audit`.
- V2 sessions use `intake_unstructured_input` and `blind_spot_audit`.
- Existing V1 acceptance tests must keep passing unless duplicated as explicit V2 equivalents.
- `run-initial-extraction` and `run-audit` may alias to V2 behavior only when the session is already V2.

A session becomes V2 only by explicit operator action:

```text
create-session SESSION_ID --protocol-version 2.0.0
```

Default remains V1:

```text
create-session SESSION_ID
```

creates `protocol_version: 1.0.0`.

A V1 session is not automatically migrated. It may remain V1 forever, or it may be explicitly upgraded by a controlled V2 intake operation:

```text
run-intake SESSION_ID --upgrade-to-v2
```

That operation must append accepted V2 intake events through the existing model-response and creation-event flow. No automatic migration based on source contents, protocol docs, or current code version is allowed.

## 2. Ledger and Entity Changes

No new durable ID prefixes. No new event types are required.

### 2.1 Ledger-Level V2 Fields

For V2 sessions the ledger adds these fields (see Section 2.5 for when they appear):

```json
{
  "protocol_version": "1.0.0 | 2.0.0",
  "session_frame": {
    "topic": "string | null",
    "downstream_use": "string | null",
    "closure_standard": "string | null",
    "input_mode": "structured | unstructured | mixed | null"
  },
  "intake_status": "not_required | required | complete",
  "blind_spot_audit_status": "not_run | complete"
}
```

### 2.2 Exact Projection Rules

Projection remains a pure fold over `events.jsonl`. It does not call the model, read a clock, mint identity, or parse `raw_output`. It may read structured, harness-written event payload fields (for example `MODEL_RESPONSE_RECORDED.payload.job`, `MODEL_RESPONSE_RECORDED.payload.accepted`, `MODEL_RESPONSE_RECORDED.payload.session_frame`, `AUDIT_RUN.payload.audit_type`), because those are validated harness output, not untrusted text. Reading them is consistent with projection purity.

`protocol_version`:
1. Initialize to `"1.0.0"`.
2. If `SESSION_CREATED.payload.protocol_version` exists, use it.
3. If any accepted `MODEL_RESPONSE_RECORDED.payload.job == "intake_unstructured_input"` exists, project `"2.0.0"`.
4. If any `AUDIT_RUN.payload.audit_type == "blind_spot"` exists, project `"2.0.0"`.
5. Later inference never downgrades an explicit `"2.0.0"` session.

`session_frame`:
1. Initialize all fields to `null`.
2. If `SESSION_CREATED.payload.session_frame` exists, project it.
3. Otherwise, project the validated `session_frame` from the first accepted `MODEL_RESPONSE_RECORDED.payload.job == "intake_unstructured_input"` whose payload carries a structured `session_frame` field (written by the harness at apply time, Decision D1).
4. If both exist, `SESSION_CREATED.payload.session_frame` wins.
5. Projection must not parse `raw_output` or call the model. The accepted intake event stores the already-validated `session_frame` as structured data, so no parsing is needed.

`intake_status`:
1. If `protocol_version == "1.0.0"`, project `"not_required"`.
2. If `protocol_version == "2.0.0"` and no `SOURCE_ADDED` exists, project `"not_required"`.
3. If `protocol_version == "2.0.0"` and at least one `SOURCE_ADDED` exists but no accepted `MODEL_RESPONSE_RECORDED.payload.job == "intake_unstructured_input"` exists, project `"required"`.
4. If there exists a single `correlation_id` that contains both an accepted intake `MODEL_RESPONSE_RECORDED` and at least one intake-created entity or work item event, project `"complete"`. This is a pure group-by-correlation check over the events.
5. Rejected or failed intake attempts do not complete intake. A `MODEL_RESPONSE_RECORDED` with `accepted == false`, an `OPERATION_FAILED`, or a `PROPOSAL_REJECTED` never contributes to completion.

`blind_spot_audit_status`:
1. Initialize to `"not_run"`.
2. If any `AUDIT_RUN.payload.audit_type == "blind_spot"` exists, project `"complete"`.
3. Failed or rejected blind-spot model calls do not complete the audit. `AUDIT_RUN` is appended only on an accepted audit, so its presence is sufficient.

### 2.3 Entity Field Additions

Prefer existing entities. All fields below default to null or empty and are omitted from the projected object when null or empty (Decision D3).

Assumption optional fields:

```json
{
  "intake_label": "CA-01 | null",
  "premise_origin": "intake | answer | blind_spot | audit | manual | null",
  "evidence_status": "verified_user_stated | model_inferred | unverified_accepted | open_dependency | external_validation_required | undecidable | null",
  "depends_on": ["A-0001"]
}
```

Work item optional fields:

```json
{
  "derived_question_label": "DQ-01 | null",
  "gap_type": "unstated_precondition | scope_boundary | authority_ownership | failure_mode | metric_definition | temporal_assumption | dependency_chain | input_completeness | contradiction | scope_conflict | blind_spot | null",
  "source_assumption_ids": ["A-0001"],
  "blocking_reason": "string | null"
}
```

### 2.4 Omit-if-null Serialization Rule

The projector serializes a V2 entity field only when its value is non-null and, for lists, non-empty. The shared canonical serializer (Section 9 of SPEC.md) is unchanged. Concretely, the projector must strip null and empty V2 fields before sorting keys, so a V1 entity (which never sets these fields) serializes to the exact bytes it does today. Byte-identical rebuild (SPEC.md acceptance tests 20, 24, 25) is preserved.

### 2.5 Conditional Ledger Shape

A session is V2 in the projection when `protocol_version == "2.0.0"` by the rules in Section 2.2. Only then does the projector emit the four ledger-level V2 fields. For a V1 session the projector emits the current V1 ledger shape with no V2 ledger fields, byte for byte. This is what allows the committed V1 sample and all V1 byte-identical tests to pass untouched.

## 3. Model Jobs

V2 uses exactly these jobs:

```text
intake_unstructured_input
rank_next_work_item
interpret_user_answer
blind_spot_audit
artifact_generation
```

`rank_next_work_item`, `interpret_user_answer`, and `artifact_generation` are upgraded in V2 but retain their V1 job names.

V1 sessions continue to support:

```text
initial_extraction
contradiction_audit
```

The harness selects the job set by session protocol version. A V1 session never runs a V2 job; a V2 session never runs a V1 job.

## 4. Validator Contracts

All validators remain handwritten unless proven insufficient. Validators run inside the existing Section 8 pipeline (`src/interrogation_harness/validation.py`): parse, schema, semantic, apply. A semantic failure appends `PROPOSAL_REJECTED` and mutates nothing.

At apply time for accepted intake, the harness writes the validated `session_frame` into the accepted `MODEL_RESPONSE_RECORDED.payload.session_frame` (Decision D1), stamps the new V2 entity fields onto creation payloads, and mints durable IDs as in V1.

### 4.1 intake_unstructured_input

Top-level contract:

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `session_frame` | yes | object | no | Exact fields only |
| `assumptions` | yes | list | no | Creation objects only |
| `work_items` | yes | list | no | Creation objects only |
| `risks` | yes | list | no | Existing V1 risk creation schema plus V2 refs |
| `terms` | yes | list | no | Existing V1 term creation schema |
| `decisions` | yes | list | no | Existing V1 decision creation schema |
| `contradictions` | yes | list | no | Existing V1 contradiction creation schema |

`session_frame`:

| Field | Required | Type | Nullable | Enum |
|---|---:|---|---:|---|
| `topic` | yes | string | yes | none |
| `downstream_use` | yes | string | yes | none |
| `closure_standard` | yes | string | yes | none |
| `input_mode` | yes | string | no | `structured`, `unstructured`, `mixed` |

Assumption creation additions:

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `tmp_handle` | yes | string | no | Must match temp handle form; durable ID rejected |
| `intake_label` | yes | string | no | Must match `CA-NN` |
| `statement` | yes | string | no | Non-empty |
| `status` | yes | string | no | Must be `candidate` |
| `source_type` | yes | string | no | Existing V1 enum |
| `source_excerpt` | yes | string | yes | Verified by harness if `user_stated` |
| `blast_radius` | yes | string | no | `high`, `medium`, `low` |
| `downstream_impact` | yes | string | no | Non-empty |
| `risk_if_wrong` | yes | string | no | Non-empty |
| `evidence_status` | yes | string | no | V2 evidence enum |
| `depends_on` | optional | list | no | Temp handles or existing durable IDs only |

Work item creation additions:

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `tmp_handle` | yes | string | no | Must match temp handle form |
| `derived_question_label` | optional | string | yes | Must match `DQ-NN` when present |
| `kind` | yes | string | no | Existing V1 work item kind enum |
| `question` | yes | string | no | Non-empty, single material question |
| `why_it_matters` | yes | string | no | Non-empty |
| `what_breaks_if_wrong` | yes | string | no | Non-empty |
| `blast_radius` | yes | string | no | `high`, `medium`, `low` |
| `blocks_closure` | yes | boolean | no | Must be true when blast radius is high |
| `gap_type` | optional | string | yes | V2 gap enum |
| `related_temp_refs` | optional | list | no | Temp handles or existing durable IDs only |
| `source_assumption_refs` | optional | list | no | Must resolve after minting |
| `answer_options` | optional | list | no | Existing answer enum only |
| `recommended_default` | optional | string | yes | Requires valid basis when non-null |
| `recommended_default_basis` | optional | string | yes | Existing durable ref or same-batch temp ref |
| `blocking_reason` | optional | string | yes | Required when `blocks_closure` is true for medium blast radius |

Semantic validation:
- No durable ID may appear in an entity creation identity field.
- Temp handles must be unique within the response.
- Every temp or durable reference must resolve after applying the accepted batch.
- `user_stated` excerpts are verified by existing provenance rules.
- High blast-radius work must block closure.
- A `medium` work item that sets `blocks_closure == true` must carry a `blocking_reason`.
- Every `DQ` work item must reference at least one source assumption unless `gap_type == "blind_spot"`.
- Visible contradictions in intake must create either a contradiction entity or a blocking work item.
- On accept, the harness stamps `intake_label`, `premise_origin = "intake"`, `evidence_status`, and resolved `depends_on` onto assumption creation payloads, and `derived_question_label`, `gap_type`, resolved `source_assumption_ids`, and `blocking_reason` onto work item creation payloads. It stores the validated `session_frame` on the accepted `MODEL_RESPONSE_RECORDED.payload`.

Rejection examples:
- `assumptions[0].id == "A-0001"`.
- `work_items[0].blocks_closure == false` with `blast_radius == "high"`.
- `derived_question_label == "DQ-01"` but no source assumption refs and `gap_type != "blind_spot"`.
- `recommended_default` non-null with missing basis.
- `medium` work item with `blocks_closure == true` and no `blocking_reason`.

### 4.2 rank_next_work_item

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `selected_work_item_id` | yes | string | no | Must resolve to unresolved `W-NNNN` |
| `question` | yes | string | no | Snapshot only |
| `why_it_matters` | yes | string | no | Snapshot only |
| `what_breaks_if_wrong` | yes | string | no | Snapshot only |
| `tested_entity_id` | yes | string | yes | Must resolve when non-null |
| `recommended_default` | yes | string | yes | Requires basis when non-null |
| `recommended_default_basis` | yes | string | yes | Must resolve when non-null |
| `allowed_answers` | yes | list | no | Existing answer enum |
| `blocking_reason` | yes | string | yes | Required when the selected item blocks closure |

Semantic validation:
- Must not create or transition anything.
- Cannot select resolved work.
- Premise-blocker priority (Decision D4): if any unresolved premise blocker exists (an unresolved work item with `blocks_closure == true`), the selected item must itself be a premise blocker. Selecting a non-blocking item while a premise blocker is unresolved is rejected. There is no curiosity override that bypasses an unresolved premise blocker; the model may only order among blockers.
- Active-item rule: if exactly one work item is already `active`, the ranker may select only that active item.
- More than one active work item indicates a corrupt projection; the operation is refused (this is also an ask-next refusal, Section 6.1).

Rejection examples:
- Selects `W-9999`.
- Selects resolved `W-0002`.
- Includes `work_items` or any creation field.
- Provides `recommended_default` without valid `recommended_default_basis`.
- Selects a non-blocking item while an unresolved `blocks_closure` item exists.

### 4.3 interpret_user_answer

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `proposed_events` | yes | list | no | Only permitted creation and transition event proposals |
| `followup_required` | yes | boolean | no | Must match proposed work status |
| `revision_required` | yes | boolean | no | True when the answer contradicts, narrows, expands, or reframes prior state |
| `warnings` | yes | list | no | Strings only |

Proposed creation payloads use the same creation rules as intake.

Proposed transition payloads:

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `from` | yes | string | no | Must equal projected current state |
| `to` | yes | string | no | Must be legal by existing state machine |
| `reason` | yes | string | no | Non-empty |
| `prior_statement` | required on revision | string | no | Must equal current primary text |
| `new_statement` | required on revision | string | no | Non-empty |
| `user_answer_event` | optional | string | no | Must resolve if present |
| `deferred_reason` | optional | string | no | Required for explicit defer when supplied |
| `resolution_work_item` | optional | string | yes | Must resolve when non-null |

Semantic validation:
- Requires exactly one active work item in the projection.
- Cannot lock an assumption unless the active answer clearly supports the lock. In practice the harness enforces this structurally: a lock transition (`-> locked`) is rejected when `followup_required == true`.
- Ambiguous answers must produce follow-up work, defer, blocked state, or open risk.
- `unknown` must not stall: it must defer, block with reason, create open risk, or create external validation work.
- `revision_required == true` must be accompanied by a revise transition (`-> revised`) carrying `prior_statement` and `new_statement`, or by a blocker work item. It may not be accompanied by a silent overwrite. `revision_required == false` may not carry a revise transition.
- Revision triggers cannot silently overwrite locked or provisional facts; the existing state machine plus the revise-preserves-prior rule enforce this.
- The model may propose events; the harness mints IDs and applies only after validation.

Rejection examples:
- `locked -> rejected`.
- `rejected -> locked`.
- Locking an assumption while `followup_required == true`.
- Revision without `prior_statement` and `new_statement`.
- `revision_required == true` with no revise transition and no blocker work item.
- Transition target does not exist.

### 4.4 blind_spot_audit

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `findings` | yes | list | no | Finding objects |
| `missing_provenance` | yes | list | no | Durable IDs only, all must resolve |
| `invalid_source_excerpts` | yes | list | no | Durable IDs only, all must resolve |
| `unresolved_material_work` | yes | list | no | Work item IDs, all must resolve |
| `artifact_blockers` | yes | list | no | Objects with valid refs |

Finding object:

| Field | Required | Type | Nullable | Enum / Rules |
|---|---:|---|---:|---|
| `kind` | yes | string | no | `contradiction`, `undefined_term`, `authority_ambiguity`, `failure_mode_omission`, `lifecycle_ambiguity`, `observability_gap`, `external_validation_needed`, `open_dependency`, `scope_conflict` |
| `refs` | yes | list | no | Durable IDs only, all must resolve |
| `severity` | yes | string | no | `high`, `medium`, `low` |
| `description` | yes | string | no | Non-empty |
| `recommended_work_item_kind` | yes | string | no | Existing work item kind enum |

Semantic validation:
- The job mutates nothing directly.
- The accepted output records `AUDIT_RUN.payload.audit_type == "blind_spot"` (Decision D2).
- The harness deterministically converts findings into ordinary entities and work items, reusing the existing V1 conversion flow (`src/interrogation_harness/audit.py`) extended for the V2 finding kinds.
- Duplicate findings must not create duplicate contradictions or duplicate blocker work. Deduplication uses the existing key (refs plus description) plus finding kind.
- High-severity converted work must block closure. Converted work sets `premise_origin = "blind_spot"` (or `"audit"`), a `gap_type` mapped from the finding kind, and `blocks_closure` per Decision D4 (high always; medium only with a `blocking_reason`).

Rejection examples:
- Finding references `A-9999`.
- Unknown finding kind.
- Missing `recommended_work_item_kind`.
- High-severity blocker converted with `blocks_closure == false`.

### 4.5 artifact_generation

| Field | Required | Type | Nullable | Rules |
|---|---:|---|---:|---|
| `artifact_markdown` | yes | string | no | Must not invent locked assumptions |
| `blocking_warnings` | yes | list | no | Strings only |
| `open_risk_register` | yes | list | no | Must include unresolved high/medium force-close items |
| `traceability_summary` | yes | list | no | Entity refs must resolve |
| `closure_status` | yes | object | no | Exact fields only |

`closure_status`:

| Field | Required | Type | Nullable | Enum / Rules |
|---|---:|---|---:|---|
| `mode` | yes | string | no | `open`, `force_closed` |
| `complete` | yes | boolean | no | False when unresolved blockers remain |
| `force_closed_event` | yes | string | yes | Must resolve to a `FORCE_CLOSED` event when non-null |

Semantic validation:
- Reads projection only.
- Cannot invent locked assumptions (existing markdown bullet check, retained).
- Cannot omit unresolved high/medium blockers after force close.
- Cannot mark force-closed incomplete work as complete: if any unresolved `blocks_closure` work item exists, `closure_status.complete` must be `false`.
- `closure_status.mode` must equal `force_closed` exactly when the projection is force-closed, and `force_closed_event` must equal the projected `force_closed_event` (or be null when not force-closed).
- Must separate locked assumptions, provisional assumptions, open risks, external validation needs, decisions, definitions, revision log, and closure mode.

Rejection examples:
- Artifact lists a locked assumption absent from projection.
- `closure_status.complete == true` while unresolved blockers exist.
- `force_closed_event` references a non-existent event.
- Open risk register omits unresolved high work after force close.

## 5. Event Mappings

Use existing event types only.

| V2 action | Existing event |
|---|---|
| Create V2 session | `SESSION_CREATED.payload.protocol_version = "2.0.0"` |
| Store session frame at creation | `SESSION_CREATED.payload.session_frame` |
| Store session frame on upgrade intake | `MODEL_RESPONSE_RECORDED.payload.session_frame` (validated, structured) |
| Add source | `SOURCE_ADDED` |
| Record intake model output | `MODEL_RESPONSE_RECORDED.payload.job = "intake_unstructured_input"` |
| Create candidate assumptions | `ASSUMPTION_CREATED` (with V2 fields stamped) |
| Create derived questions | `WORK_ITEM_CREATED` (with V2 fields stamped) |
| Create contradiction/risk/term/decision | Existing creation events |
| Ask selected work | `WORK_ITEM_STATUS_CHANGED`, then `QUESTION_ASKED` |
| Interpret answer | Existing transition and creation events |
| Record blind-spot audit | `AUDIT_RUN.payload.audit_type = "blind_spot"` |
| Convert blind-spot findings | Existing creation and transition events |
| Force close | `FORCE_CLOSED` |
| Generate artifact | `ARTIFACT_GENERATED` |

No new event type is necessary for V2. The only payload additions are structured fields on existing events: `protocol_version` and `session_frame` on `SESSION_CREATED`, `session_frame` on the accepted intake `MODEL_RESPONSE_RECORDED`, `audit_type` on `AUDIT_RUN`, and the V2 entity fields on creation events.

## 6. Blocking Semantics

Separate four concepts. The premise-blocker predicate is Decision D4: an unresolved work item with `blocks_closure == true`.

### 6.1 Blocks ask-next Entirely

`ask-next` must refuse to ask anything only when:
- V2 session has source and `intake_status == "required"`.
- More than one work item is already active, indicating corrupt projection.
- One active work item exists and the ranker selects a different item.
- The prior answer operation failed semantic validation and left no legal transition or disposition for the active item.
- Session is force-closed, unless an explicit reopen behavior is later specified.

### 6.2 Controls Next-Question Priority

These must not deadlock ask-next. They force `rank_next_work_item` to select a premise blocker. They are enforced at creation time so that each is represented as a work item with `blocks_closure == true` (or a `blocking_reason` for medium severity), and they carry a `gap_type` from the list below:
- Open high/medium contradiction (`gap_type: contradiction` or `scope_conflict`).
- Undefined critical term (`gap_type: metric_definition`).
- Authority ambiguity (`gap_type: authority_ownership`).
- Failure-path omission (`gap_type: failure_mode`).
- Scope conflict (`gap_type: scope_conflict`).
- Open dependency (`gap_type: dependency_chain`).
- Unresolved high-blast-radius assumption (the work item that tests it).
- Blind-spot finding converted to open work (`gap_type: blind_spot` or the mapped kind).

Because each is a `blocks_closure` work item, ranking selects it ahead of non-blocking curiosity work by the single predicate in Decision D4. No separate priority engine is required.

### 6.3 Blocks Normal Completion and Artifact Generation

Normal artifact generation is blocked when any unresolved `blocks_closure` work item exists.

In V2, high blast-radius work always blocks closure. Medium work blocks closure only when the harness or accepted model output gives a `blocking_reason`.

### 6.4 May Pass Only Through Force Close

The following may permit artifact generation only after `FORCE_CLOSED`:
- Unresolved high-blast-radius work.
- Unresolved high/medium contradiction.
- External validation required but not completed.
- Undecidable outcome-determinative assumption.
- Required blind-spot audit completed but produced unresolved blockers.

Force close is controlled incomplete closure. It must not mark work resolved, promote assumptions to locked, accept risks, or claim success.

## 7. CLI Changes

Preserve all V1 commands.

Add:

```text
create-session SESSION_ID --protocol-version 2.0.0
run-intake SESSION_ID
run-intake SESSION_ID --upgrade-to-v2
run-blind-spot-audit SESSION_ID
```

Compatibility rules:

```text
run-initial-extraction
```
- V1 session: runs `initial_extraction`.
- V2 session: aliases to `run-intake`.

```text
run-audit
```
- V1 session: runs `contradiction_audit`.
- V2 session: aliases to `run-blind-spot-audit`.

```text
force-close
```
- V1 session: existing audit-first behavior.
- V2 session: runs blind-spot audit first, then appends `FORCE_CLOSED`.

No CLI command may silently upgrade a V1 session except explicit `run-intake --upgrade-to-v2`. `--protocol-version` defaults to `1.0.0` when omitted, so plain `create-session` is unchanged.

## 8. Mock Policy

"No monkey patching the mock" means:
- Do not add ad hoc conditional mock behavior merely to satisfy a failing test.
- Do add named deterministic V2 mock scenarios.
- Each V2 scenario has explicit raw JSON output and is selectable by name (extend the existing `MockScenario` enum and `RESPONSES` table in `src/interrogation_harness/model/mock.py`).
- Do not extend the existing dynamic `interpret confirm` helper for V2. V2 answer-interpretation scenarios are static named entries.
- V2 acceptance tests must use named scenarios for: intake, ranking, answer interpretation (confirm, reject, revise, defer, unknown, ambiguous), blind-spot audit, artifact generation, malformed output, illegal transition, invalid refs, and force-close artifact behavior.
- The mock remains offline and deterministic.

Required new scenario names (illustrative, final names chosen at implementation):

```text
intake_unstructured_input
intake_durable_id_in_creation        (rejection: durable ID in creation)
intake_dq_without_source             (rejection: DQ without source assumption)
intake_high_blast_not_blocking       (rejection: high blast radius, blocks_closure false)
rank_next_work_item_v2
rank_skip_blocker                    (rejection: selects non-blocker while blocker open)
interpret_user_answer:ambiguous      (must not lock)
blind_spot_audit
blind_spot_audit_invalid_refs        (rejection)
artifact_generation_v2
artifact_force_closed_incomplete     (closure_status complete false)
```

## 9. Acceptance Tests

V2 must prove premise control, not just a larger prompt. These run offline against the deterministic mock, alongside the full V1 suite.

1. V1 sessions still run existing `initial_extraction` and `contradiction_audit`.
2. V2 session creation records `SESSION_CREATED.payload.protocol_version == "2.0.0"`.
3. V1 session is not silently upgraded by `add-source`, `ask-next`, or `run-audit`.
4. `run-intake --upgrade-to-v2` explicitly upgrades a V1 session through accepted intake events.
5. Ledger projects `protocol_version`, `session_frame`, `intake_status`, and `blind_spot_audit_status` only from the defined event sources, and only for V2 sessions.
6. V2 source with required intake blocks `ask-next` until accepted intake completes.
7. Accepted intake creates assumptions and derived questions using harness-minted IDs.
8. Intake DQ without a valid source assumption is rejected unless `gap_type == "blind_spot"`.
9. High-blast-radius work with `blocks_closure: false` is rejected.
10. Durable IDs in creation fields are rejected.
11. Rank selects unresolved premise blockers before non-blocking work.
12. Rank does not deadlock on undefined term, authority ambiguity, failure-path omission, or contradiction.
13. Ambiguous answer cannot lock an assumption.
14. Revision trigger creates a revision or blocker, never a silent overwrite.
15. `unknown` creates risk, external validation, deferred work, or blocked work and does not stall.
16. Blind-spot audit records `AUDIT_RUN.payload.audit_type == "blind_spot"`.
17. Blind-spot audit with invalid refs is rejected without mutation.
18. The harness converts blind-spot findings deterministically into existing entities and work items.
19. Force close runs the blind-spot audit first in V2.
20. Force close preserves unresolved blockers and does not relabel them.
21. Artifact after force close marks closure incomplete.
22. Artifact includes unresolved high/medium blockers in open risks or blocking warnings.
23. Artifact cannot invent locked assumptions.
24. Rebuild from events remains byte-identical, for both V1 and V2 sessions.
25. Existing V1 acceptance tests still pass, and the committed V1 sample is byte-identical.

## 10. Non-Goals

No replacement harness. No second ledger or premise state machine. No automatic migration. No automatic web research. No prompt-only enforcement. No new event type unless a later implementation proves existing events cannot represent the required state. No runtime dependency unless handwritten validation is proven inadequate. No weakening of force-close semantics. No change to the V1 ledger or event bytes for V1 sessions.

## 11. Implementation Stages

Each stage ends green: the full V1 suite plus all V2 tests added so far pass offline, and a commit is made. V1 byte-identical checks (tests 20, 24, 25) gate every stage.

1. Add protocol-version activation to `create-session`, defaulting to V1. Store `protocol_version` (and `session_frame` when supplied) in `SESSION_CREATED.payload`. No projection change yet beyond reading `protocol_version`.
2. Add projection rules for the four V2 ledger fields from existing events, emitted only for V2 sessions (Section 2.5). Verify V1 ledgers are unchanged.
3. Add optional V2 entity fields to records and projection with omit-if-null serialization (Section 2.4). Verify V1 ledgers are unchanged.
4. Add V2 model job names while retaining V1 jobs, and route job selection by protocol version.
5. Add handwritten validator contracts for the V2 jobs, including the apply-time stamping of V2 fields and `session_frame` (Decision D1).
6. Add `run-intake` and V2-aware command aliasing, including `--upgrade-to-v2`.
7. Upgrade rank priority semantics using the premise-blocker predicate (Decision D4) without introducing ask-next deadlocks (Section 6.1).
8. Upgrade answer interpretation semantic validation, including `revision_required` consistency.
9. Add `blind_spot_audit` behavior through existing `AUDIT_RUN` with `audit_type`, and extend deterministic finding conversion.
10. Upgrade force-close and artifact validation for V2 incomplete closure, including `closure_status`.
11. Add named V2 mock scenarios (Section 8).
12. Add V2 acceptance tests (Section 9) while keeping V1 tests passing, and add a V2 sample session built through the real harness.
