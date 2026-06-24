# Trading Risk Gate Notes

Trading signals are derived from the market data stream.

The execution gateway owns order placement.

The risk gate can veto orders before they reach the gateway.

Operators may force close incomplete handoffs when unresolved blockers remain visible.

Unknowns:

- Manual override ownership during reconnect is not specified.
- Feed gap reconnect behavior still requires validation against venue rules.
