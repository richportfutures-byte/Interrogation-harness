# V2 Pass C: Premise Answer Assimilation

Proceed with Protocol Runtime Pass 1 of 3: V2 Answer Assimilation.

Use this document as the authoritative source prompt for the goal-backed implementation pass. Keep working until the pass is implemented, verified, committed, pushed if explicitly asked, and ready for the user to run, unless a hard stop condition is reached.

For ordinary failures, do not stop. Diagnose, fix, and continue. This includes failing tests, validation gaps, schema mismatches, mock scenario gaps, sample drift caused by your changes, doc contradictions, and implementation bugs. Use targeted tests while iterating, then run full verification before committing.

## Hard Stop Conditions

Stop and report only if:

- The working tree is dirty before coding in files relevant to this pass and the changes cannot be safely distinguished from this work.
- V1 preservation would require weakening V2 premise-control behavior.
- Existing event types truly cannot represent the required behavior.
- Projection would need to parse raw model output.
- The implementation would require trusting model-proposed truth without harness validation.
- V1 sample drift cannot be eliminated after investigation and attempted fix.
- Active work item binding cannot be represented through the existing request and validation contract without a schema change that would break V1.
- Revision mechanics cannot be represented without changing V1 behavior.
- Completing this pass would require implementing blind-spot audit, force-close redesign, or final artifact upgrades.

## Repository Context

Project root:

```bash
/Users/stu/Projects/interrogation-harness
```

GitHub mirror:

```text
richportfutures-byte/Interrogation-harness
```

Expected base:

```text
a956a0a V2 Pass B: premise blocker ranking
```

Known last verification:

```text
uv run pytest                       # 139 passed
uv run python scripts/build_sample_session.py
git diff -- sessions/               # empty
git diff --check                    # passed
uv run python -m interrogation_harness --help
```

## Objective

Implement V2 answer assimilation for `interpret_user_answer`.

A V2 session must be able to:

1. Ask or select a premise-control work item.
2. Accept an answer for the active item.
3. Validate the model's interpretation against active work binding, provenance, refs, state transitions, revision flags, and blocker rules.
4. Apply only lawful existing events.
5. Create answer-origin assumptions with harness-finalized evidence.
6. Create follow-up work that obeys D5 and participates in Pass B ranking.
7. Represent revisions, contradictions, risks, and pushback without silent overwrite.
8. Preserve V1 behavior and V1 sample byte identity.

## Core Doctrine

The model proposes. The harness decides.

The harness owns:

- durable IDs
- state transitions
- evidence finalization
- provenance validation
- reference validation
- blocker semantics
- active-work binding
- rejection handling
- event persistence
- ledger projection

Do not introduce:

- a second ledger
- a second state machine
- new durable ID prefixes
- projection parsing of `raw_output`
- runtime dependencies
- broad restructuring

Use existing event types unless they are genuinely incapable. If existing event types cannot safely represent the behavior, stop and report before adding a new event type.

## Preflight

Run:

```bash
git status --short
git log --oneline -10
uv run pytest
uv run python scripts/build_sample_session.py
git diff -- sessions/
```

If the working tree is dirty, inspect the dirty files. If they are unrelated, leave them alone and continue. If they overlap this pass and cannot be safely preserved, stop and report.

Before coding, read:

```text
docs/PREMISE_CONTROL_PROTOCOL_V2.md
docs/V2_IMPLEMENTATION_SPEC.md
src/interrogation_harness/validation.py
src/interrogation_harness/model/jobs.py
src/interrogation_harness/model/schemas.py
src/interrogation_harness/model/mock.py
src/interrogation_harness/state_machine.py
src/interrogation_harness/projection.py
```

Also inspect tests covering:

- V1 `interpret_user_answer`
- V2 intake
- V2 evidence finalization
- V2 blocker ranking
- sample session byte identity

## Scope

In scope:

- V2 semantic validation for `interpret_user_answer`.
- Active work item binding.
- Legal resolution of the active V2 work item.
- V2 answer-origin assumption creation.
- V2 answer-origin work item creation.
- Evidence finalization for answer-origin assumptions.
- Provenance verification against the respondent answer text for answer-origin `user_stated` claims.
- Reference validation for answer-origin records.
- Revision representation using existing events.
- Pushback and follow-up representation using existing events.
- Preservation of Pass B blocker priority after answers.
- Deterministic V2 mock scenarios where useful for runtime flows.
- Focused tests.

Out of scope:

- blind-spot audit
- final artifact upgrades
- force-close redesign
- external validation workflow
- live model adapter
- UI work
- new dependencies
- broad docs rewrite

## Active Work Binding

For V2 sessions, `interpret_user_answer` must require exactly one active work item.

Required behavior:

1. If no active work item exists, reject.
2. If more than one active work item exists, reject.
3. `WORK_ITEM_STATUS_CHANGED` proposals may target only the active work item.
4. Entity transitions may target related records when legally linked to the active answer.
5. A model may not resolve or transition a different work item while one active item exists.
6. Do not add `answered_work_item_id` unless the existing active-work request contract is genuinely insufficient. Prefer the existing `active_work_item` request payload.

## Work Item Resolution Rules

A V2 work item may be resolved only through legal transitions on the active work item.

Reject proposals that:

- target nonexistent work
- target already resolved work
- target a non-active work item
- use wrong `from` status
- use illegal state transitions
- mutate unrelated state without valid refs
- resolve active work while suppressing a required represented blocker, contradiction, risk, or revision

Allow resolving the active item while creating a new unresolved blocker only if that blocker, contradiction, or risk is explicitly represented with valid existing events and links.

## Answer-Origin Assumption Rules

When V2 `interpret_user_answer` creates assumptions:

1. Stamp `premise_origin: answer`.
2. Do not require `intake_label`.
3. Finalize `evidence_status` in the harness.
4. Verify `user_stated` excerpts against the respondent answer text, not `source.md`.
5. Verified `user_stated` finalizes to `verified_user_stated`.
6. Unverifiable `user_stated` downgrades to `model_inferred` and `evidence_status: model_inferred`.
7. `model_inferred` finalizes to `model_inferred` unless an allowed preservable status applies.
8. `external_required` finalizes to `external_validation_required`.
9. Never permit `source_type: model_inferred` with `evidence_status: verified_user_stated`.
10. `depends_on` may reference only existing durable IDs or valid same-proposal temp handles.
11. Durable IDs inside creation identity fields are rejected.

## Answer-Origin Work Item Rules

When V2 `interpret_user_answer` creates work items, enforce D5:

- High blast-radius work must block closure.
- High blockers do not require `blocking_reason`.
- Medium blockers require non-empty `blocking_reason`.
- Low blast-radius work must not block closure.

Validate refs, same-proposal temp handles, `target_entity`, `source_assumption_ids`, and `recommended_default_basis`.

Follow-up work created from an answer should preserve linkage through existing fields where available:

- `target_entity`
- `source_assumption_ids`
- `derived_question_label`
- `gap_type`
- `related_temp_refs`

## Revision Mechanics

Use existing events and legal transitions.

V2 schema may include V2-only fields such as `revision_required`, but preserve V1 compatibility. Do not globally require new fields for V1 outputs.

For V2:

- If `revision_required == true`, require either a legal revise transition or a valid represented blocker, contradiction, risk, or follow-up work item.
- If a revise transition is present, require prior and new text fields and preserve revision history through existing projection behavior.
- Reject silent overwrites of locked or provisional material.
- Reject replacement assumptions with no valid linkage when linkage is required.
- Reject resolving active work while suppressing a material revision.

If the state machine lacks a necessary transition, add only the smallest explicit transition that preserves V1 behavior, and prove it with tests.

## Pushback and Follow-Up

Do not implement blind-spot audit.

Do validate immediate answer-assimilation outcomes for:

- contradiction
- scope conflict
- authority ambiguity
- failure-path omission
- undefined term
- new dependency
- unsupported confidence
- external validation requirement

The harness should validate structured representation. It does not need to infer semantic truth from prose beyond the structured proposal and provenance checks.

## Preserve Pass B Semantics

After V2 answer interpretation:

1. If the active blocker is resolved and no blockers remain, ask-next may select the next lawful unresolved item.
2. If the active blocker remains unresolved, ask-next must continue selecting it.
3. If the answer creates a new blocker, ask-next must select a blocker before non-blocking work.
4. Unresolved blockers must not deadlock ask-next.

## V1 Preservation

V1 must remain unchanged:

- V1 sessions do not require V2 fields.
- V1 `interpret_user_answer` behavior remains compatible.
- V1 projection emits no V2-only fields.
- V1 commands do not silently upgrade.
- V1 sample regeneration produces no `sessions/` diff.
- Do not rewrite V1 tests to accommodate V2.

## Mock and Tests

Add focused tests, likely:

```text
tests/test_v2_pass_c_answer_assimilation.py
```

Use deterministic named mock scenarios for happy-path runtime flows where appropriate. For adversarial validator cases, raw scripted adapters are acceptable and preferred when they keep the test focused.

Required coverage:

1. V2 resolves active work through legal transition.
2. V2 rejects resolving non-active work.
3. V2 rejects no active or multiple active work.
4. V2 rejects nonexistent refs.
5. V2 rejects wrong entity-type transitions.
6. V2 rejects `from` mismatch.
7. Answer-origin assumptions get `premise_origin: answer`.
8. Valid answer excerpt verifies to `verified_user_stated`.
9. Invalid answer excerpt downgrades to `model_inferred`.
10. `external_required` finalizes to `external_validation_required`.
11. `model_inferred + verified_user_stated` never reaches ledger.
12. Follow-up blocking work obeys D5.
13. Reject high non-blocking work.
14. Reject medium blocker without `blocking_reason`.
15. Reject low blocker.
16. Validate `recommended_default_basis`.
17. Represent revision through legal linked records or transitions.
18. Reject silent revision.
19. Ranking selects next blocker after active blocker resolves.
20. Ranking keeps selecting unresolved active blocker when it remains unresolved.
21. Ranking selects newly created blocker before non-blocking work.
22. Ask-next does not deadlock after answer interpretation.
23. V1 `interpret_user_answer` remains unchanged.
24. Existing tests pass.
25. V1 sample regeneration produces no diff.
26. CLI loads.

## Docs

Do not update docs just to narrate this pass.

Update `docs/V2_IMPLEMENTATION_SPEC.md` only if implementation exposes an actual contradiction, missing contract, or obsolete statement. If docs change, report exactly what changed and why.

## Likely Files

Modify only what is needed. Likely files:

```text
src/interrogation_harness/validation.py
src/interrogation_harness/model/schemas.py
src/interrogation_harness/model/mock.py
src/interrogation_harness/model/jobs.py
src/interrogation_harness/state_machine.py
tests/test_v2_pass_c_answer_assimilation.py
```

## Verification

Before committing, run:

```bash
uv run pytest
uv run python scripts/build_sample_session.py
git diff -- sessions/
git diff --check
uv run python -m interrogation_harness --help
```

If any command fails, diagnose and fix. Re-run targeted tests as needed, then re-run full verification.

Commit only if:

- pytest passes
- sample rebuild succeeds
- `git diff -- sessions/` is empty
- `git diff --check` passes
- CLI loads

Commit:

```bash
git add src tests
git add docs/V2_IMPLEMENTATION_SPEC.md   # only if legitimately changed
git commit -m "V2 Pass C: premise answer assimilation"
```

## Final Report

After committing, report:

1. Files changed.
2. Tests passed.
3. V1 sample diff result.
4. `git diff --check` result.
5. CLI load result.
6. Commit hash.
7. Deviations.
8. Specification contradictions discovered.
9. Runtime capability added.
10. What remains for Protocol Runtime Pass 2 of 3.

## Success Criteria

This pass is complete only when a V2 session can:

1. Select a premise-control work item.
2. Accept an answer for that active item.
3. Validate interpretation against active work, provenance, refs, state, revision, and blocker rules.
4. Resolve active work only through lawful transitions.
5. Create answer-origin assumptions with harness-finalized evidence.
6. Create follow-up blockers that obey D5.
7. Represent revisions or contradictions without silent overwrite.
8. Preserve blocker-aware ranking and ask-next after interpretation.
9. Preserve V1 behavior and sample byte identity.
10. Pass full verification and commit cleanly.
