"""Source excerpt provenance checks, Section 11."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from interrogation_harness.records import SourceType

_WHITESPACE = re.compile(r"\s+")


def normalize_excerpt_text(text: str) -> str:
    """Collapse whitespace and trim text for source excerpt matching."""
    return _WHITESPACE.sub(" ", text).strip()


def source_excerpt_verified(source_markdown: str, excerpt: str | None) -> bool:
    """Return whether ``excerpt`` appears in ``source_markdown`` after normalization."""
    if not excerpt:
        return False
    normalized_source = normalize_excerpt_text(source_markdown)
    normalized_excerpt = normalize_excerpt_text(excerpt)
    return bool(normalized_excerpt) and normalized_excerpt in normalized_source


def apply_assumption_provenance(
    assumption_payload: dict[str, Any], source_markdown: str
) -> dict[str, Any]:
    """Return a payload copy with Section 11 provenance policy applied.

    A missing or unverifiable ``user_stated`` excerpt is downgraded to
    ``model_inferred`` and kept. The downgrade reason remains in the creating event
    payload for auditability, while the projector simply ignores the extra key.
    """
    payload = deepcopy(assumption_payload)
    if payload.get("source_type") != SourceType.USER_STATED.value:
        payload["source_excerpt_verified"] = False
        return payload

    if source_excerpt_verified(source_markdown, payload.get("source_excerpt")):
        payload["source_excerpt_verified"] = True
        return payload

    payload["source_type"] = SourceType.MODEL_INFERRED.value
    payload["source_excerpt_verified"] = False
    payload["provenance_downgrade_reason"] = (
        "user_stated source_excerpt did not verify against source.md"
    )
    return payload
