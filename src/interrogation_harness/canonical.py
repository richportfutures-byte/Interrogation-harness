"""Section 9 canonical serialization, shared by storage writes and later rebuild.

This is the single shared serialization point. Both the event log writer and the
ledger writer (and, in a later stage, the ledger rebuild) MUST go through these
functions so the log and ledger are Git diffable and byte stable.

Key sorting is delegated to ``json.dumps(..., sort_keys=True)`` and is recursive at
every object level. Array element order is NOT changed here: producers control element
order. The Section 9 rule that entity arrays are sorted by ``id`` ascending is the
projector's responsibility (a later stage), applied before the ledger dict reaches
``dumps_ledger``.

These functions return text. Byte level concerns (UTF-8 encoding, LF line endings) are
handled by the writer in :mod:`interrogation_harness.session_store`.
"""

from __future__ import annotations

import json
from typing import Any


def dumps_event_line(obj: dict[str, Any]) -> str:
    """Serialize one ``events.jsonl`` line.

    Compact JSON, keys sorted lexicographically, no spaces after separators, and no
    trailing newline (the writer appends the LF that separates lines).
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dumps_ledger(obj: Any) -> str:
    """Serialize a full ``ledger.json`` document.

    Keys sorted lexicographically at every level, two space indent, and a single
    trailing newline. With ``indent`` set, ``json`` uses a ``","`` item separator, so no
    line carries trailing whitespace.
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def loads(text: str) -> Any:
    """Parse canonical JSON text (one event line or a full ledger document)."""
    return json.loads(text)
