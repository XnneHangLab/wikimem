"""Append-only operations journal.

One JSON line per mutation. ``tail -f journal.jsonl`` is the live answer to
"what happened to my memory" — no database inspection tools required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._serialize import now_iso


class Journal:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(
        self,
        action: str,
        *,
        category: str,
        name: str,
        owner: str | None = None,
        source_conv: str | None = None,
        detail: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": now_iso(),
            "action": action,
            "category": category,
            "item": name,
        }
        if owner is not None:
            entry["owner"] = owner
        if source_conv is not None:
            entry["source_conv"] = source_conv
        if detail is not None:
            entry["detail"] = detail
        self._write(entry)

    def append_diary(
        self,
        *,
        date: str,
        time: str,
        owner: str | None = None,
        source_conv: str | None = None,
    ) -> None:
        """Record a diary append (ADR-0001) in the same log as wiki writes.

        Diary shares one journal with wiki but has its own line shape:
        ``action`` is ``"diary"`` and the target is ``date`` + ``time`` rather
        than ``category`` + ``item`` — a reader tells the two apart by
        ``action``.
        """
        entry: dict[str, Any] = {
            "ts": now_iso(),
            "action": "diary",
            "date": date,
            "time": time,
        }
        if owner is not None:
            entry["owner"] = owner
        if source_conv is not None:
            entry["source_conv"] = source_conv
        self._write(entry)

    def _write(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
