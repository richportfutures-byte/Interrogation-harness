"""SessionStore: the filesystem boundary for a single session (Section 3).

Owns the session directory layout and all file IO. It reads and writes bytes through
the shared canonical serializer for the ledger; it does not build the ledger (no
projection), mint identity, or interpret events. Those belong to later stages.

All text is written as UTF-8 with LF line endings by encoding to bytes explicitly, so
output is identical regardless of host platform.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import canonical

# Section 3: session_id MUST be filesystem safe. Restrict to a conservative safe set
# and forbid the directory traversal names.
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")

_SOURCE_FILE = "source.md"
_EVENTS_FILE = "events.jsonl"
_LEDGER_FILE = "ledger.json"
_ARTIFACT_FILE = "final_artifact.md"


class SessionStore:
    """File access for ``<root>/<session_id>/`` per the Section 3 layout."""

    def __init__(self, root: str | Path, session_id: str) -> None:
        if not _SAFE_SESSION_ID.match(session_id) or session_id in (".", ".."):
            raise ValueError(f"session_id is not filesystem safe: {session_id!r}")
        self.root = Path(root)
        self.session_id = session_id
        self.dir = self.root / session_id

    # -- paths -------------------------------------------------------------

    @property
    def source_path(self) -> Path:
        return self.dir / _SOURCE_FILE

    @property
    def events_path(self) -> Path:
        return self.dir / _EVENTS_FILE

    @property
    def ledger_path(self) -> Path:
        return self.dir / _LEDGER_FILE

    @property
    def artifact_path(self) -> Path:
        return self.dir / _ARTIFACT_FILE

    # -- session directory -------------------------------------------------

    def create(self) -> None:
        """Create the session directory (idempotent)."""
        self.dir.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        return self.dir.is_dir()

    # -- source.md ---------------------------------------------------------

    def source_exists(self) -> bool:
        return self.source_path.is_file()

    def write_source(self, content: str) -> None:
        """Write ``source.md``, replacing any existing contents."""
        self._write_text(self.source_path, content)

    def append_source(self, content: str) -> None:
        """Append to ``source.md`` (repeated add-source), creating it if absent."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.source_path, "ab") as handle:
            handle.write(content.encode("utf-8"))

    def read_source(self) -> str:
        return self.source_path.read_text(encoding="utf-8")

    # -- events.jsonl ------------------------------------------------------

    def append_event_line(self, line: str) -> None:
        """Append one already serialized event line, followed by a single LF."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.events_path, "ab") as handle:
            handle.write((line + "\n").encode("utf-8"))

    def read_event_lines(self) -> list[str]:
        """Return the non-empty lines of ``events.jsonl`` in file order."""
        if not self.events_path.is_file():
            return []
        text = self.events_path.read_text(encoding="utf-8")
        return [line for line in text.split("\n") if line]

    # -- ledger.json -------------------------------------------------------

    def ledger_exists(self) -> bool:
        return self.ledger_path.is_file()

    def write_ledger(self, ledger: object) -> None:
        """Write ``ledger.json`` through the shared canonical serializer."""
        self._write_text(self.ledger_path, canonical.dumps_ledger(ledger))

    def read_ledger(self) -> object:
        return canonical.loads(self.ledger_path.read_text(encoding="utf-8"))

    def delete_ledger(self) -> None:
        """Remove ``ledger.json`` if present (it is rebuildable and disposable)."""
        if self.ledger_path.exists():
            self.ledger_path.unlink()

    # -- final_artifact.md -------------------------------------------------

    def write_artifact(self, markdown: str) -> None:
        self._write_text(self.artifact_path, markdown)

    # -- export ------------------------------------------------------------

    def export(self, dest: str | Path) -> list[Path]:
        """Copy the session files that exist into ``dest``; return the copied paths."""
        dest_dir = Path(dest)
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        for path in (
            self.source_path,
            self.events_path,
            self.ledger_path,
            self.artifact_path,
        ):
            if path.is_file():
                target = dest_dir / path.name
                shutil.copy2(path, target)
                copied.append(target)
        return copied

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
