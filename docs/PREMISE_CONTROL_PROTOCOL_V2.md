# Premise Control Protocol v2

## Status

This document is the refined protocol that combines the v1 architecture with the added unstructured-input intake provision. It is written as an operational protocol, not meeting notes.

## 1. Purpose and Standard

This protocol exists to identify, test, revise, and lock assumptions that materially affect downstream design, implementation, operations, or decision quality.

The protocol is designed to prevent false confidence. It treats ambiguity, contradiction, unstated dependencies, and retroactive reinterpretation as audit failures unless they are explicitly surfaced, resolved, or carried forward as open risks.

This is a blocking protocol. The session does not advance when a material contradiction, undefined term, unresolved dependency, or scope conflict remains active.

The protocol applies when auditing:
- Product or system designs.
- Trading workflows, data pipelines, or execution systems.
- Architecture proposals.
- Operational procedures.
- Strategy documents.
- Any free-form or structured explanation that will later be used as implementation truth.

## 2. Session Frame and Definitions

### 2.1 Roles

- **Auditor**: The party running the protocol, responsible for question sequencing, contradiction detection, assumption labeling, and lock management.
- **Respondent**: The party providing the underlying claims, requirements, corrections, and clarifications.
- **Working Record**: The live artifact that stores assumptions, answers, revisions, unresolved issues, and locks.

### 2.2 Operative Units

- **Assumption**: A claim treated as true for downstream reasoning, whether explicitly stated or implicitly required.
- **Confirmed Assumption**: An assumption that has been tested sufficiently for current session scope and explicitly locked.
- **Derived Question (DQ)**: A question generated from a detected gap in a claim or input block.
- **Revision Event**: A new answer that changes, narrows, deprecates, or contradicts a prior confirmed or provisional assumption.
- **Blast Radius**: The amount of downstream reasoning, design, or documentation invalidated if an assumption is wrong.
- **Lock**: Explicit confirmation that the current wording is the authoritative version for the session.

### 2.3 Session Objective

Before substantive questioning begins, the auditor must state:
- The system or topic under audit.
- The intended downstream use of the output.
- The decision boundary for “good enough to proceed.”
- Whether the session starts from structured inputs, unstructured inputs, or both.

### 2.4 Standard of Evidence

The protocol does not require absolute certainty. It requires explicit treatment of uncertainty.

If a claim cannot be verified during the session but materially affects correctness, it must be tagged as one of:
- Unverified but accepted for now.
- Open dependency.
- External validation required.
- Undecidable within current session scope.

## 3. Sequential Questioning and Context Carry-Forward

### 3.1 One Question at a Time

The auditor asks one material question at a time.

A new question cannot be asked until the prior answer has been processed through all of the following steps:
1. Extract operative facts.
2. Compare those facts against the current working assumption set.
3. Detect contradiction, narrowing, expansion, or dependency introduction.
4. Update the working record.
5. Decide whether the answer is locked, revised, or requires immediate follow-up.

Asking stacked or compound questions is prohibited unless the sub-parts are operationally inseparable.

### 3.2 Context Carry-Forward

After every answer, the auditor must update the working assumption set before advancing.

This update must include:
- New assumptions introduced by the answer.
- Terms whose meaning changed.
- Dependencies now implied.
- Prior assumptions affected by the new answer.
- Any answer that changes the scope boundary.

No answer is treated as isolated. Every answer is evaluated against all prior locked and provisional assumptions.

### 3.3 Follow-Up Rules

A follow-up question is permitted only if it is necessary for one of the following reasons:
- The prior answer is ambiguous in a way that affects implementation or judgment.
- The answer introduces a contradiction.
- The answer contains a material undefined term.
- The answer affects a high-blast-radius assumption.
- The answer changes who owns authority, failure handling, or boundary conditions.

Curiosity is not sufficient. Follow-up must be justified by downstream impact.

### 3.4 Locking Rule

When an answer is sufficiently precise for current scope, the auditor must restate the operative assumption in normalized form and request explicit lock.

Example pattern:

> “Locking Assumption E as: ‘The stream is started on launch, not lazily on first view.’ Confirm?”

Until explicit confirmation is received, the item remains provisional.

## 4. Anti-Sycophancy and Pushback Triggers

### 4.1 Requirement

The auditor must resist conversational smoothing that weakens rigor.

Affirmations that do not improve precision are treated as noise. Examples include bridge phrases such as “Great answer,” “Makes sense,” or similar verbal padding when a contradiction or ambiguity is still active.

### 4.2 Pushback Is Blocking

When a pushback trigger fires, the session does not advance until the issue is resolved, explicitly deferred, or converted into an open risk with documented reason.

### 4.3 Pushback Trigger Table

The auditor must intervene when any of the following conditions appear:

| Trigger | Description | Required Auditor Action |
|---|---|---|
| False tradeoff framing | The respondent presents two options as exhaustive when other materially plausible options exist. | Name the false binary and require expansion or justification. |
| Scope creep without acknowledgment | New functionality, authority, or constraint is introduced without stating that scope changed. | Pause and restate the new scope boundary before proceeding. |
| Retroactive justification | A new explanation attempts to make an earlier answer appear compatible after the fact without explicit revision. | Force a revision event under §5. |
| Undefined critical term | A key term is used without operational meaning, metric, or test. | Require definition before relying on the term. |
| Authority ambiguity | It is unclear which component, actor, or system is authoritative. | Force explicit ownership assignment. |
| Failure-path omission | Happy-path behavior is described while failure behavior remains undeclared. | Block until failure behavior is specified or marked open risk. |
| Confidence without support | The respondent expresses certainty that exceeds the specificity of the answer. | Separate confidence from evidence and restate uncertainty. |
| Internal contradiction | A new claim conflicts with an earlier claim or lock. | Stop and reconcile immediately. |
| Treating narrative as specification | A descriptive text is being treated as complete truth without gap extraction. | Run §11 before further reasoning. |

### 4.4 Pushback Style

Pushback should be direct, minimal, and specific.

Preferred patterns:
- “That conflicts with Assumption B as currently locked.”
- “You just changed scope. We need to name that explicitly.”
- “That answer defines the happy path only. What is the failure behavior?”
- “You are presenting a binary. What other viable cases exist?”

## 5. Retroactive Revision Mechanics

### 5.1 When Revision Is Required

A revision event is mandatory when a new answer:
- Contradicts a prior locked or provisional assumption.
- Narrows or expands the meaning of a prior assumption.
- Changes implementation ownership.
- Reframes a previously settled boundary condition.
- Makes an earlier summary materially misleading.

### 5.2 Revision Procedure

When revision is triggered, the auditor must perform all of the following:
1. Name the prior assumption by label.
2. Quote or restate the currently locked wording.
3. State what the new answer implies.
4. Ask whether the prior assumption is being replaced, narrowed, or split.
5. Record the outcome in the revision log.
6. Re-lock the authoritative wording.

### 5.3 Revision Log Format

Each revision event must capture:
- Revision ID.
- Affected assumption label(s).
- Prior wording.
- New wording.
- Reason for revision.
- Downstream artifacts impacted.
- Confirmation status.

### 5.4 Retroactive Reprocessing

If a revision changes the assumption base materially, the auditor must re-check any downstream assumptions that depended on the superseded version.

This includes queued questions, partial summaries, draft outputs, and any earlier “resolved” item whose validity depended on the old wording.

## 6. Termination Criteria and Move-On Rules

### 6.1 Necessity Standard

The auditor moves on only when the current item is sufficiently resolved for current scope.

“Sufficiently resolved” means:
- The assumption is stated in operational terms.
- Contradictions have been resolved or explicitly logged.
- Downstream dependence is understood.
- Any residual uncertainty has a named status.

### 6.2 Curiosity vs Necessity

The auditor must distinguish useful exploration from required clarification.

The session should not continue probing a point solely because it is interesting. Additional questioning must stop when further detail will not materially change design, decision, implementation, controls, or risk handling.

### 6.3 Stop Conditions

The session ends when one of the following is true:
- All high- and medium-blast-radius assumptions are locked or explicitly classified as open risks.
- Remaining questions are low-value and non-material.
- The respondent cannot provide additional information and the unresolved items are documented.
- The session objective defined in §2.3 has been met.

### 6.4 Hard Stop Condition

The auditor must not claim the audit is complete if a critical assumption remains both unverified and outcome-determinative.

In that case, the session output must state that the protocol stopped short of full closure and identify the required external validation path.

## 7. Output Document Standards

### 7.1 Output Purpose

The final artifact must function as implementation-grade ground truth for the audited scope.

It is not a chat recap, meeting summary, or narrative transcript.

### 7.2 Required Sections in the Output Artifact

The output document must include:
- Scope and objective.
- Locked assumptions register.
- Revision log.
- Open risks and undecidable assumptions.
- Authority map where relevant.
- Failure-mode declarations where relevant.
- Definitions for critical terms.
- Items explicitly excluded from scope.
- Validation actions still required.

### 7.3 Assumption Register Format

Each locked assumption entry should contain:
- Assumption ID.
- Final wording.
- Status: locked / provisional / open risk / externally dependent.
- Rationale.
- Dependencies.
- Blast radius.
- Source answer reference.

### 7.4 Output Quality Bar

A valid output document must be:
- Internally consistent.
- Explicit about uncertainty.
- Separated into authoritative statements versus open questions.
- Specific enough that a downstream implementer does not need to infer hidden logic.

If the document would force a downstream team to guess, the audit is incomplete.

## 8. Auditor Blind Spot Register

### 8.1 Purpose

Before closing the session, the auditor must run a blind-spot check to catch assumptions that often remain invisible even in otherwise strong sessions.

This is mandatory because some high-risk assumptions are rarely volunteered by respondents without prompting.

### 8.2 Core Blind Spot Categories

The blind-spot review must at minimum test for:
- Authority confusion.
- Failure behavior omission.
- Boundary and lifecycle ambiguity.
- Feedback loop closure.
- Observability and reconciliation gaps.
- Hidden framework or vendor lock-in.
- Time-dependent behavior.
- Human override paths.

### 8.3 Trading-System Weighted Checks

For trading or market-connected systems, explicitly inspect:
- P&L or ledger authority confusion.
- Order authority versus signal authority.
- Stream failure behavior.
- Feed gap and reconnect semantics.
- Session-boundary behavior.
- Risk gate ownership.
- Reconciliation source of truth.
- Feedback loop closure between execution, state, and reporting.
- Framework lock-in masked as architecture choice.

### 8.4 Blind Spot Handling

Any blind spot that cannot be resolved during the session is entered into the output artifact as an open risk or undecidable assumption, not silently ignored.

## 9. Session Anti-Patterns

The auditor must actively avoid the following failure modes:

| Anti-Pattern | Why It Fails | Required Countermeasure |
|---|---|---|
| Premature summarization | Creates false closure before contradictions are reconciled. | Delay summary until locks exist. |
| Moving on without locking | Leaves downstream reasoning attached to ambiguous wording. | Force explicit lock after normalization. |
| Accepting narrative as specification | Converts descriptive prose into false authority. | Run §11 intake and derive missing questions. |
| Over-follow-up from curiosity | Consumes session bandwidth without changing outcomes. | Apply necessity test from §6. |
| Missing retroactive revision | Preserves stale assumptions after new answers land. | Trigger §5 immediately. |
| Smoothing over contradiction | Rewards coherence theater instead of correctness. | Use blocking pushback. |
| Hidden scope expansion | Pollutes the audit with unacknowledged change. | Restate and lock new scope boundary. |
| Conflating confidence with evidence | Makes weak answers sound settled. | Separate claim, evidence, and uncertainty. |
| Unlabeled unresolved risk | Causes downstream teams to assume silent approval. | Classify every unresolved material item. |

## 10. Protocol Reuse Notes

### 10.1 Domain Adaptability

This protocol is reusable across domains because its core mechanics are structural rather than topic-specific.

The reusable core includes:
- Sequential questioning.
- Context carry-forward.
- Blocking pushback.
- Revision handling.
- Necessity-based follow-up.
- Output normalization.
- Blind-spot review.

### 10.2 What to Keep Stable

The following should remain stable across domains:
- Locking discipline.
- Revision log requirements.
- Stop conditions.
- Anti-pattern enforcement.
- The distinction between authoritative statements and open risks.

### 10.3 What to Adapt

The following should be domain-tuned:
- Blind-spot register examples.
- Authority map specifics.
- Failure-mode prompts.
- Definitions of correctness and acceptable uncertainty.
- Domain-specific weighted gap types in §11.

### 10.4 Reuse Rule

Do not adapt the protocol by weakening blocking behavior. Adapt by changing the domain-specific prompts and risk categories while preserving audit discipline.

## 11. Unstructured Input Intake

### 11.1 Purpose

When the session starts from a free-form text block rather than a structured question set, the auditor must derive the missing inputs and required questions before entering the main questioning flow.

This section prevents the common failure of treating an unstructured narrative as though it were already a complete specification.

### 11.2 Intake Trigger

Run this section whenever the starting material includes any of the following:
- Narrative descriptions.
- Design notes.
- Email or chat excerpts.
- Product briefs.
- Code comments.
- Problem statements.
- Mixed structured and unstructured notes.

### 11.3 Intake Procedure

Execute the following steps before entering §3.

#### Step 1 — Surface Extraction

Parse the text block and extract every explicit declarative claim, stated intention, named dependency, stated constraint, boundary claim, and operational promise.

Label each as a candidate assumption:
- `CA-01`, `CA-02`, `CA-03`, and so on.

Do not evaluate truth yet. The objective in this step is complete extraction, not judgment.

#### Step 2 — Gap Detection

For each candidate assumption, run the following gap taxonomy.

| Gap Type | Trigger Question Pattern |
|---|---|
| Unstated precondition | What must be true for this assumption to hold? |
| Scope boundary | What does this explicitly exclude, and is that exclusion intentional? |
| Authority / ownership | Who or what is authoritative for this claim or action? |
| Failure mode | What breaks if this is wrong, unavailable, late, or partial? |
| Metric / definition | How is the key term measured, tested, or operationally defined? |
| Temporal assumption | When is this valid, and how does it change over time, state, or session boundary? |
| Dependency chain | What dependencies are required but not declared? |
| Input completeness | What information is implicitly required but missing from the text? |

Each triggered gap produces one or more derived questions.

#### Step 3 — Derived Question Generation

Create a **Derived Question (DQ)** for every material gap.

Each DQ must:
- Reference its source candidate assumption.
- Name the fired gap type.
- Use implementation-grade wording.
- Be phrased so the answer can be normalized into a lockable assumption.

#### Step 4 — Priority Sort

Rank DQs by blast radius.

Ask first the questions whose answers would invalidate or reshape the largest number of other assumptions, dependencies, or design decisions.

#### Step 5 — Coverage Check

Before entering §3, verify all of the following:
- Every candidate assumption has at least one DQ or is explicitly marked self-contained.
- DQs are de-duplicated.
- Candidate assumptions that cannot be resolved by questioning are marked undecidable.
- Contradictions already visible inside the input block are flagged immediately rather than deferred.

### 11.4 Derived Question Register

Before the first live question is asked, produce a register using this format:

```text
DQ-01 [from CA-03] — Gap type: Failure mode
“If the stream connection drops at session open, what is the recovery behavior and who owns that path?”
Blast radius: HIGH — affects CA-03, CA-07, CA-11

DQ-02 [from CA-01] — Gap type: Authority/ownership
“When you say ‘the system writes P&L,’ which process has ledger authority — the strategy, the adapter, or an external reconciler?”
Blast radius: HIGH — affects CA-01, CA-09
```

This register becomes the intake-generated queue for §3.

### 11.5 Mid-Session Discovery Rule

If a new free-form block or a materially new narrative appears mid-session, the auditor must re-run §11 for that input before continuing ordinary questioning.

New candidate assumptions discovered mid-session are tagged `[mid-session]` and inserted into the working record.

### 11.6 Interaction with Other Sections

- With **§3**, the DQ register becomes the ordered input queue for one-question-at-a-time auditing.
- With **§4**, contradictions found during intake trigger pushback before normal progression.
- With **§5**, if a later answer invalidates a candidate assumption previously treated as self-contained, that item must be re-run through gap detection and re-queued as `[retroactive]`.
- With **§8**, undecidable intake assumptions are pre-seeded into the blind-spot register.
- With **§9**, skipping §11 when inputs are unstructured is itself an anti-pattern.

### 11.7 Domain Weighting Note

The gap taxonomy is domain-neutral, but priority weighting should be domain-specific.

For trading systems, the highest-yield early checks are usually:
- Authority / ownership.
- Failure mode.
- Temporal assumption.

## Operating Procedure Summary

Use the protocol in this order:
1. Establish scope and objective under §2.
2. If inputs are unstructured, run §11 first.
3. Ask one question at a time under §3.
4. Apply blocking pushback under §4 whenever triggered.
5. Process revisions under §5 immediately when they occur.
6. Use §6 to decide whether to continue or stop.
7. Run the blind-spot check in §8 before closure.
8. Produce the implementation-grade output under §7.
9. Review anti-patterns in §9 as a final quality control pass.

## Minimal Deliverables Checklist

A session is not complete unless it leaves behind all of the following:
- Locked assumptions register.
- Revision log.
- Open risks register.
- Declared exclusions.
- Definitions for critical terms.
- Authority map where applicable.
- Failure behavior where applicable.
- External validation items where required.

## Enforcement Principle

The protocol is only as strong as its blocking behavior.

If ambiguity, contradiction, undefined ownership, or unprocessed narrative input is allowed to pass unchallenged, the session may feel productive while producing an unreliable ground-truth artifact.
