# Premise Control Artifact V2

## Scope and Objective

- Topic: trading risk gate
- Downstream use: implementation handoff
- Closure standard: locked authority and failure behavior or explicit incomplete closure
- Input mode: unstructured
- Source hash: 532a0cbc2b4ca0c63a72a0e7d62a71ce609690fd235c558bdc8bd6277a6f5997

## Closure Status

- Mode: force_closed
- Complete: false
- Intake status: complete
- Blind-spot audit status: complete
- Force-close event: E-0023
- Closure is controlled incomplete closure, not success.

## Locked Assumptions

- A-0001: Trading signals are derived from the market data stream. Status: locked. Blast radius: high. Evidence: verified_user_stated. Dependencies: none. Source answer events: none recorded.

## Provisional and Unconfirmed Assumptions

- A-0002: The execution gateway owns order placement. Status: candidate. Blast radius: high. Evidence: verified_user_stated. Dependencies: none. Source answer events: none recorded.
- A-0003: Manual override ownership during reconnect is not specified. Status: candidate. Blast radius: high. Evidence: model_inferred. Dependencies: none. Source answer events: none recorded.
- A-0004: Feed gap reconnect behavior requires external validation against venue rules. Status: candidate. Blast radius: high. Evidence: external_validation_required. Dependencies: A-0001. Source answer events: none recorded.

## Revision Log

None

## Open Risks and Undecidable Assumptions

- W-0002 (high work item): Who owns manual override decisions during reconnect?
- W-0003 (high work item): Who can override the risk gate during reconnect?
- A-0004 (external_validation_required): Feed gap reconnect behavior requires external validation against venue rules.

## Authority Map

- A-0002: The execution gateway owns order placement.
- A-0003: Manual override ownership during reconnect is not specified.
- W-0002 (open): Who owns manual override decisions during reconnect?
- W-0003 (open): Who can override the risk gate during reconnect?

## Failure-Mode Declarations

- A-0003: Manual override ownership during reconnect is not specified.
- A-0004: Feed gap reconnect behavior requires external validation against venue rules.

## Definitions for Critical Terms

- risk gate: The component that can veto orders before execution.

## Decisions

None

## Items Explicitly Excluded From Scope

- No exclusions recorded in the projection.

## Validation Actions Still Required

- A-0004: Feed gap reconnect behavior requires external validation against venue rules.
- W-0002: Who owns manual override decisions during reconnect?
- W-0003: Who can override the risk gate during reconnect?

## Open Work Items

- W-0002 (high, open): Who owns manual override decisions during reconnect?
- W-0003 (high, open): Who can override the risk gate during reconnect?

## Contradictions and Reconciliation

None

## Provenance Index

- A-0001: origin=intake, source=user_stated, evidence=verified_user_stated, verified=True, excerpt='Trading signals are derived from the market data stream.'
- A-0002: origin=intake, source=user_stated, evidence=verified_user_stated, verified=True, excerpt='The execution gateway owns order placement.'
- A-0003: origin=intake, source=model_inferred, evidence=model_inferred, verified=False, excerpt=None
- A-0004: origin=blind_spot, source=external_required, evidence=external_validation_required, verified=False, excerpt=None

## Downstream Builder Instructions

- Treat the event log and ledger as the source of truth.
- Use locked assumptions as authoritative for the audited scope.
- Do not treat provisional, model-inferred, undecidable, or externally dependent assumptions as confirmed facts.
- Do not treat this artifact as complete closure.

## Known Limits

- Unresolved closure-blocking work remains.
- Outcome-determinative external validation remains.
