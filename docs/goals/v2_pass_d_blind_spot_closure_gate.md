Proceed with Protocol Runtime Pass 2 of 3: V2 Blind-Spot Audit, Open-Risk Conversion, and Closure Gate.

This is an implementation instruction for this pass only. It is subordinate to:

- `docs/PREMISE_CONTROL_PROTOCOL_V2.md`
- `docs/V2_IMPLEMENTATION_SPEC.md`
- runtime behavior
- tests

Do not treat this goal document as a durable specification. If implementation exposes a missing or contradictory contract, update `docs/V2_IMPLEMENTATION_SPEC.md` narrowly and report the exact correction. Do not let `docs/goals/*` become a third protocol layer.

## 0. Repository Context

Project root:

```bash
/Users/stu/Projects/interrogation-harness
```

GitHub mirror:

```text
richportfutures-byte/Interrogation-harness
```

Expected code base:

```text
3f8d7b5 V2 Pass C: premise answer assimilation
```

The implementation goal may start from a docs-only commit that adds this source document on top of `3f8d7b5`; that is acceptable as long as the working tree is clean before coding.

Known Pass C state:

- Pass C was pushed at `3f8d7b5`.
- This goal source document may be committed as a docs-only setup commit on top of `3f8d7b5`.
- Tests last passed with `161 passed`.
- V1 sample regeneration last produced no `sessions/` diff.
- Pass A implemented V2 intake.
- Pass A.1 implemented harness-finalized evidence status.
- Pass B implemented premise-blocker ranking.
- Pass C implemented answer assimilation.
- This pass implements the pre-closure protocol layer: blind-spot audit, conversion of audit findings into existing record types, and closure eligibility enforcement.

## 1. Objective

Implement the V2 blind-spot audit runtime and closure gate.

A V2 session must not reach normal closure merely because the original intake queue and answered work items are exhausted. Before normal closure or normal artifact eligibility is allowed, the harness must run the protocol's blind-spot audit, validate the model's proposed findings, convert unresolved material into existing event-backed records, and enforce closure eligibility based on unresolved blockers.

This pass must make closure meaningful.

## 2. Persistence Rule

Keep working through ordinary implementation problems until the pass is complete.

Do not stop merely because:

- a test fails
- schema validation needs to be tightened
- deterministic mocks need another scenario
- existing helper code needs a small refactor
- a command needs a clearer error
- docs need a narrow correction to match implementation
- verification exposes an issue that can be fixed within this pass

Fix those issues and re-run verification.

Stop without committing only for the explicit stop conditions in Section 22, or if proceeding would require weakening V1 or trusting model output as authoritative truth.

## 3. Core Doctrine

The model proposes. The harness decides.

The model may propose blind-spot findings, follow-up work, risks, contradictions, or assumptions. The harness owns:

- durable IDs
- event creation
- state transitions
- reference validation
- evidence finalization
- blocker semantics
- audit status
- closure eligibility
- force-close semantics
- ledger projection

The model must never become authoritative for truth, risk status, closure, or completeness.

## 4. Architecture Constraints

Do not introduce:

- a second ledger
- a second state machine
- a parallel blind-spot record store
- a new "undecidable item" type
- a new normal-close event or command unless the durable spec already requires it
- new durable ID prefixes
- projection logic that parses `raw_output`
- model-owned durable IDs
- model-owned state mutation
- silent V1-to-V2 migration
- runtime dependencies
- final V2 artifact content generation

Do not add new event types unless existing events cannot safely represent the required behavior. If a new event type appears necessary, stop and report the blocker before implementing it.

Blind-spot findings must be represented through existing event-backed concepts, including where applicable:

- `RISK_CREATED`
- `WORK_ITEM_CREATED`
- `CONTRADICTION_CREATED`
- ordinary assumption creation/update fields
- `evidence_status: undecidable`
- `evidence_status: external_validation_required`

Do not create a separate blind-spot ledger or finding registry if existing events and ledger fields can represent the outcome.

## 5. Preflight

Run:

```bash
git status --short
git log --oneline -12
uv run pytest
uv run python scripts/build_sample_session.py
git diff -- sessions/
```

If the working tree is dirty before coding, stop and report the dirty files. The goal source document itself should already be committed before this goal starts.

Before writing code, inspect:

```text
docs/PREMISE_CONTROL_PROTOCOL_V2.md
docs/V2_IMPLEMENTATION_SPEC.md
src/interrogation_harness/audit.py
src/interrogation_harness/artifact.py
src/interrogation_harness/interrogation.py
src/interrogation_harness/validation.py
src/interrogation_harness/model/jobs.py
src/interrogation_harness/model/schemas.py
src/interrogation_harness/model/mock.py
src/interrogation_harness/state_machine.py
src/interrogation_harness/projection.py
tests/test_v2_pass_b_ranking.py
tests/test_v2_pass_c_answer_assimilation.py
```

Also inspect existing tests for:

```text
force-close
artifact generation
closure behavior
risk creation
contradiction creation
work item creation
V1 sample byte identity
```

## 6. Scope

In scope:

1. Implement the V2 `blind_spot_audit` job as a real runtime path.
2. Add or complete the smallest model schema needed for blind-spot audit proposals.
3. Validate blind-spot audit proposals.
4. Convert audit findings into existing event-backed records.
5. Project V2 `blind_spot_audit_status` from structured event fields only.
6. Enforce V2 closure eligibility.
7. Ensure V2 normal closure or normal artifact eligibility requires a completed blind-spot audit.
8. Ensure unresolved closure blockers prevent normal closure and normal artifact generation.
9. Ensure V2 force-close remains controlled incomplete closure, not success.
10. Ensure V2 force-close runs or requires blind-spot audit first unless the existing command contract makes that impossible.
11. Add minimal V2 artifact eligibility or `closure_status` support needed to prevent false success; leave final V2 artifact content for Pass 3.
12. Preserve V1 behavior and V1 sample byte identity.

Out of scope:

- final V2 artifact prose/layout upgrade
- canonical V2 sample session
- external validation workflow
- live model adapter
- UI work
- new persistent stores
- broad documentation rewrite
- new dependencies

## 7. Blind-Spot Audit Runtime

Implement `blind_spot_audit` as a V2-only job.

Required behavior:

1. V1 `run-audit` must remain the existing contradiction audit. V1 must not emit V2-only fields.
2. V2 `run-audit` must alias to V2 blind-spot audit. Add `run-blind-spot-audit` only if it is missing and fits the existing CLI shape.
3. V2 sessions may run blind-spot audit only after intake has completed.
4. Direct blind-spot audit should reject when an active work item exists unless the durable V2 spec clearly permits audit with active work. Choose the stricter closure-safe behavior if ambiguous.
5. V2 force-close should attempt or require blind-spot audit first. If active work prevents ordinary audit, either use a force-close-specific incomplete path that preserves active work as unresolved, or reject force-close before appending `FORCE_CLOSED`. Do not silently skip audit.
6. Blind-spot audit must inspect the current ledger state, not raw model output.
7. Blind-spot audit model output must be recorded like other model responses and accepted audit runs must append `AUDIT_RUN.payload.audit_type == "blind_spot"`.
8. Accepted audit output must create ordinary harness-owned events for material unresolved findings.
9. Projection must derive audit status from structured events, not from `raw_output`.
10. Running audit with no material findings must still produce a structured accepted result that marks the audit complete.

Use the existing status vocabulary from `docs/V2_IMPLEMENTATION_SPEC.md`:

```text
blind_spot_audit_status: not_run | complete
```

Do not introduce `not_started`, `completed`, or `blocked` unless implementation proves the durable spec must change.

## 8. Required Blind-Spot Categories

The audit must support, at minimum, the protocol categories:

- authority confusion
- failure behavior omission
- boundary or lifecycle ambiguity
- feedback loop closure
- observability or reconciliation gap
- hidden framework or vendor lock-in
- time-dependent behavior
- human override path

For trading or market-connected systems, support weighted checks for:

- P&L or ledger authority confusion
- order authority versus signal authority
- stream failure behavior
- feed gap and reconnect semantics
- session-boundary behavior
- risk gate ownership
- reconciliation source of truth
- execution/state/reporting feedback loop closure
- framework lock-in masked as architecture choice

Do not hard-code trading-only behavior as universal. Domain weighting may affect audit prompts or deterministic mock scenarios, but runtime validation must remain domain-neutral unless the existing session frame explicitly declares a trading or market-connected scope.

## 9. Blind-Spot Finding Conversion

Blind-spot findings must be converted into existing record types.

Allowed conversion targets:

1. Work item:
   - Use when the finding requires respondent clarification or follow-up.
   - Apply Decision D5 blocker rules.
   - Preserve category/source linkage through existing fields.
2. Risk:
   - Use when the issue is known but unresolved, deferred, accepted for now, externally dependent, or cannot be resolved in-session.
3. Contradiction:
   - Use when the finding identifies incompatible assumptions or claims.
4. Assumption:
   - Use when the audit discovers an unstated assumption that must be recorded.
   - Apply ordinary V2 evidence-status finalization.
5. No-op / covered:
   - Use only when the finding is already represented by existing assumptions, risks, contradictions, or work items.
   - Must cite valid existing record IDs.

Prefer the current durable spec shape for `blind_spot_audit` findings. If that shape cannot express the required conversion targets, add the smallest optional V2-compatible schema fields needed and update `docs/V2_IMPLEMENTATION_SPEC.md` narrowly to prevent future confusion. Do not add a new durable entity type.

## 10. D5 Closure-Blocking Rules

Apply Decision D5 exactly.

Required behavior:

1. High blast-radius work always blocks closure.
2. High blast-radius work does not require `blocking_reason`.
3. Medium blast-radius work blocks closure only when represented as:

```text
blocks_closure: true
blocking_reason: non-empty
```

4. Medium work may also be non-blocking if validly represented that way.
5. Low blast-radius work does not block closure.
6. Low blast-radius work with `blocks_closure: true` must be rejected.

Do not replace D5 with a generic "high/medium blocks closure" rule. Ranking and ask-next still use the Pass B premise-blocker predicate: unresolved work item with `blocks_closure == true`.

## 11. Open-Risk Conversion Rules

Open-risk conversion must stay inside existing event types.

The audit may classify unresolved material as:

- open risk
- external validation required
- undecidable within current session scope
- unverified but accepted for now
- follow-up work required
- contradiction requiring reconciliation

Represent these through existing records and fields.

Examples:

- External dependency: create or update an assumption with `evidence_status: external_validation_required`, or create a risk/work item linked to the dependency.
- Undecidable issue: create or update an assumption with `evidence_status: undecidable`, or create a risk explaining why it is undecidable.
- Required clarification: create a blocking or non-blocking work item according to D5.
- Known unresolved issue: create `RISK_CREATED`.
- Incompatible claims: create `CONTRADICTION_CREATED`.

Do not add a new undecidable entity type.

## 12. Closure Gate

Implement V2 closure eligibility enforcement. The repo currently has force-close and artifact generation; do not invent a new normal-close command or event just to satisfy this pass. Gate the existing normal artifact path and add a small internal closure-eligibility helper if useful.

Normal closure or normal artifact generation must be rejected when any of the following is true:

1. Intake is required or incomplete.
2. Blind-spot audit is not complete.
3. Any unresolved work item with `blocks_closure == true` exists.
4. Any active work item exists.
5. Any unresolved contradiction exists, unless the durable spec or existing state model explicitly classifies it as deferred/non-blocking.
6. Any required external validation item is outcome-determinative and not explicitly carried as an open risk, external dependency, undecidable assumption, or force-close incompleteness reason.
7. The ledger is in an invalid state that would make closure misleading.

Normal closure must not be blocked merely because non-blocking low or medium work remains unresolved.

If existing artifact-generation commands can produce a normal artifact despite unresolved V2 blockers or missing blind-spot audit, add a gate that refuses normal artifact generation until closure eligibility is satisfied. Do not implement the final V2 artifact format in this pass.

## 13. Force-Close Semantics

Preserve the V1 doctrine:

```text
Force-close is controlled incomplete closure, not success.
```

For V2 sessions:

1. Force-close must not mark unresolved work as resolved.
2. Force-close must not mark unresolved risks or contradictions as resolved.
3. Force-close must not convert external dependencies into verified claims.
4. Force-close must preserve unresolved blockers in the ledger.
5. Force-close must emit or preserve a state that downstream artifact generation can identify as incomplete.
6. Force-close should run blind-spot audit first for V2 when possible.
7. If force-close cannot run blind-spot audit because of active work or the existing command model, it must reject before `FORCE_CLOSED` or record the missing audit/active work as an explicit incompleteness reason using existing fields/events.
8. Force-close must not permit a success artifact path that hides unresolved material.

If existing force-close behavior cannot support this without changing core V1 semantics, stop and report the required minimal design change.

## 14. Audit Status Projection

V2 `blind_spot_audit_status` must be projected deterministically from structured events.

Use the existing V2 projection convention:

```text
not_run | complete
```

Projection must not:

- inspect model `raw_output`
- call the model
- read clocks
- mint IDs
- infer completion from absence of findings alone unless a structured accepted audit event exists

V1 ledgers must not emit V2-only audit fields.

## 15. Model Schema Requirements

Prefer the smallest schema extension necessary.

Blind-spot audit model output must be able to express:

- no material findings
- finding category
- finding severity or blast radius
- finding description
- linked existing record IDs
- proposed conversion using existing creation semantics
- whether the issue blocks closure under D5
- evidence status where assumption creation is proposed
- external validation or undecidable status where relevant
- covered/no-op findings with valid existing record IDs

Validation must reject:

- unsupported conversion target types
- invalid finding categories if categories are enumerated
- nonexistent linked refs
- durable IDs inside creation payloads
- `model_inferred + verified_user_stated`
- `external_required` not finalized to `external_validation_required`
- high blast-radius non-blocking work
- medium blocking work without `blocking_reason`
- low blocking work
- no-op findings that cite nonexistent covered records
- audit output that claims completion while omitting required conversion for material findings

## 16. Deterministic Mock Scenarios

Add deterministic named mock scenarios for V2 blind-spot audit.

Required scenarios:

1. Audit finds no material blind spots and marks audit complete.
2. Audit finds authority confusion and creates blocking work.
3. Audit finds failure-path omission and creates blocking work.
4. Audit finds external validation requirement and creates risk or assumption with `external_validation_required`.
5. Audit finds undecidable issue and records it through existing fields/records.
6. Audit finds contradiction and creates a contradiction record.
7. Audit finding is already covered by existing records and performs a validated no-op.
8. Audit tries to create high blast-radius non-blocking work and is rejected.
9. Audit tries to create medium blocking work without `blocking_reason` and is rejected.
10. Audit tries to create low blocking work and is rejected.
11. Audit cites nonexistent covered records and is rejected.
12. Audit tries to mint durable IDs and is rejected.
13. Audit claims completion while failing to convert a material finding and is rejected.

Do not let deterministic mock support alter V1 sample output.

## 17. Required Tests

Add a focused test file unless an existing file is clearly the correct location.

Suggested file:

```text
tests/test_v2_pass_d_blind_spot_closure_gate.py
```

Required coverage:

1. V1 `run-audit` remains contradiction audit and does not emit V2 fields.
2. V2 `run-audit` aliases to blind-spot audit.
3. V2 cannot run blind-spot audit before intake completion.
4. V2 direct blind-spot audit rejects or safely handles active work according to the implemented closure-safe contract.
5. V2 blind-spot audit with no findings marks audit complete.
6. V2 blind-spot audit creates blocking work for authority confusion.
7. V2 blind-spot audit creates blocking work for failure-path omission.
8. V2 blind-spot audit can create external-validation risk or assumption.
9. V2 blind-spot audit can record undecidable material through existing records/fields.
10. V2 blind-spot audit can create contradiction records.
11. V2 blind-spot audit can validate no-op findings covered by existing records.
12. V2 blind-spot audit rejects high blast-radius non-blocking work.
13. V2 blind-spot audit rejects medium blocking work without `blocking_reason`.
14. V2 blind-spot audit rejects low blocking work.
15. V2 blind-spot audit rejects nonexistent linked refs.
16. V2 blind-spot audit rejects durable IDs inside creation payloads.
17. V2 blind-spot audit rejects invalid evidence-status combinations.
18. V2 normal artifact eligibility rejects when blind-spot audit has not completed.
19. V2 normal artifact eligibility rejects when unresolved closure blockers exist.
20. V2 normal artifact eligibility allows non-blocking unresolved work to remain.
21. V2 normal artifact eligibility rejects when an active work item exists.
22. V2 force-close preserves unresolved blockers and does not mark them resolved.
23. V2 force-close records or preserves incomplete closure semantics.
24. V2 force-close does not allow a successful normal artifact path that hides unresolved blockers.
25. V2 artifact eligibility is blocked by closure blockers without implementing final V2 artifact content.
26. Pass B blocker ranking still works after audit-created blockers.
27. Pass C answer assimilation can resolve audit-created blockers.
28. Existing tests pass.
29. V1 sample regeneration produces no diff under `sessions/`.
30. CLI loads.

## 18. Documentation Rules

Do not update documentation merely to narrate this pass.

Update `docs/V2_IMPLEMENTATION_SPEC.md` only if implementation exposes an actual contradiction, missing contract, or obsolete statement that would mislead future implementation.

If docs are changed, the final report must identify the contradiction or missing contract and the exact correction.

## 19. Expected Files

Likely changed files:

```text
src/interrogation_harness/audit.py
src/interrogation_harness/artifact.py
src/interrogation_harness/interrogation.py
src/interrogation_harness/validation.py
src/interrogation_harness/model/jobs.py
src/interrogation_harness/model/schemas.py
src/interrogation_harness/model/mock.py
src/interrogation_harness/projection.py
src/interrogation_harness/state_machine.py
tests/test_v2_pass_d_blind_spot_closure_gate.py
```

Possible documentation file if required:

```text
docs/V2_IMPLEMENTATION_SPEC.md
```

Only modify files required to implement this pass.

Do not restructure unrelated code.

## 20. Verification

Before committing, run:

```bash
uv run pytest
uv run python scripts/build_sample_session.py
git diff -- sessions/
git diff --check
uv run python -m interrogation_harness --help
```

Required results:

```text
pytest passes
sample session rebuild succeeds
git diff -- sessions/ is empty
git diff --check passes
CLI loads
```

If the implementation touches closure or artifact eligibility, run an additional V2 smoke flow proving:

```text
create V2 session
run intake
ask next
answer active work
run blind-spot audit
attempt normal artifact generation with blockers
force-close with blockers
confirm unresolved blockers remain unresolved
confirm incomplete closure is visible
```

## 21. Commit Rule

Commit only if all verification commands pass and `git diff -- sessions/` is empty.

Use:

```bash
git add src tests
```

If documentation was legitimately required:

```bash
git add docs/V2_IMPLEMENTATION_SPEC.md
```

Commit message:

```bash
git commit -m "V2 Pass D: blind spot audit and closure gate"
```

## 22. Final Report

After committing, report exactly:

1. Files changed.
2. Tests passed.
3. V1 sample diff result.
4. `git diff --check` result.
5. CLI load result.
6. Extra V2 smoke-flow result.
7. Commit hash.
8. Deviations from this instruction.
9. Specification contradictions or missing contracts discovered.
10. Runtime capability added.
11. What remains for Protocol Runtime Pass 3 of 3.

## 23. Stop Conditions

Stop without committing only if any of the following remain true after reasonable inspection and attempts to fix:

1. Working tree is dirty before coding.
2. V1 preservation requires weakening V2 premise-control behavior.
3. Existing event types cannot safely represent blind-spot findings.
4. A new persistent blind-spot entity appears necessary.
5. Projection would need to parse raw model output.
6. The only way to proceed would trust model-proposed truth without harness validation.
7. V1 sample drift cannot be eliminated.
8. Force-close cannot preserve controlled incomplete closure without changing core V1 semantics.
9. Normal closure or artifact eligibility cannot be gated without implementing full V2 artifact generation.
10. Implementing this pass requires external validation workflow or final artifact content.

Do not use these stop conditions for ordinary build failures, test failures, missing mocks, narrow schema additions, or documentation clarifications that can be fixed within the pass.

## 24. Success Criteria

This pass is complete only when a V2 session can:

1. Complete intake.
2. Select and answer premise-control work.
3. Run blind-spot audit before normal closure or normal artifact eligibility.
4. Convert material blind-spot findings into existing assumptions, work items, risks, or contradictions.
5. Apply D5 exactly to audit-created work.
6. Mark blind-spot audit complete only through structured accepted events.
7. Reject normal closure or normal artifact eligibility while closure blockers remain.
8. Allow non-blocking unresolved work to remain without blocking normal closure.
9. Preserve force-close as controlled incomplete closure.
10. Prevent normal artifact eligibility from hiding unresolved blockers.
11. Preserve V1 behavior and V1 sample byte identity.
12. Pass the full verification suite and commit cleanly.
