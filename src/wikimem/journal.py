"""Append-only operations journal.

One JSON line per mutation. ``tail -f journal.jsonl`` is the live answer to
"what happened to my memory" — no database inspection tools required.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
