# Messy Payment Harness Notes

We need the payment system to be implementation grade, but these notes are uneven.

Payments require idempotency keys.

The billing worker owns payment writes.

Operators may force close a handoff, but unresolved high-risk questions must stay visible.

Unknowns:

- The exact retry limit is not confirmed.
- The processor outage behavior still needs a decision.
