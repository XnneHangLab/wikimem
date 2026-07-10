"""Storage layer: one markdown file per category, ``##`` sections as items.

Serialization format (human-first — the file IS the database):

.. code-block:: markdown

    # preferences

    ## likes-the-sea

    喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

    <!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->

Reading is tolerant (hand edits must never crash a read); writing is strict
(validated names, atomic replace, journal entry per mutation).
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .journal import Journal
from .models import MemoryItem

_CATEGORY_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
_ITEM_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_META_RE = re.compile(r"^<!--\s*wikimem:\s*(.*?)\s*-->\s*$")
_JOURNAL_FILENAME = "journal.jsonl"


def validate_category(category: str) -> str:
    """Categories are ASCII slugs: they double as filenames and link prefixes."""
    if not _CATEGORY_RE.match(category):
        raise ValueError(
            f"invalid category {category!r}: expected lowercase slug like 'daily_life'"
        )
    return category


def sanitize_item_name(name: str) -> str:
    """Item names may be any language, but must stay heading- and link-safe."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("item name is empty")
    if any(tok in cleaned for tok in ("[[", "]]", ":", "|", "#")):
        raise ValueError(f"item name {cleaned!r} contains reserved characters ([[ ]] : | #)")
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_meta(line: str) -> dict[str, str] | None:
    m = _META_RE.match(line.strip())
    if not m:
        return None
    fields: dict[str, str] = {}
    for part in m.group(1).split("|"):
        key, _, value = part.strip().partition("=")
        if key and value:
            fields[key.strip()] = value.strip()
    return fields


def _meta_value(value: str) -> str:
    # '|' is the field separator inside the metadata comment.
    return value.replace("|", "/").strip()


class MemoryStore:
    """Read/write access to a directory of category markdown files."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.journal = Journal(self.root / _JOURNAL_FILENAME)
        # Bumped on every successful in-process write; lets derived state
        # (e.g. MemoryIndex) rebuild lazily. Out-of-band file edits are not
        # detected — rebuild the index explicitly after those.
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    # ---------------------------------------------------------------- reads

    def categories(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.stem for p in self.root.glob("*.md"))

    def items(self, category: str | None = None) -> list[MemoryItem]:
        cats = [category] if category is not None else self.categories()
        out: list[MemoryItem] = []
        for cat in cats:
            out.extend(self._read_category(cat))
        return out

    def get(self, category: str, name: str) -> MemoryItem | None:
        wanted = " ".join(name.split())
        for item in self._read_category(category):
            if item.name == wanted:
                return item
        return None

    # --------------------------------------------------------------- writes

    def add(
        self,
        category: str,
        name: str,
        content: str,
        *,
        owner: str | None = None,
        source_conv: str | None = None,
        ts: str | None = None,
    ) -> MemoryItem:
        """Insert a new item, or replace the same-named item (update)."""
        validate_category(category)
        item = MemoryItem(
            category=category,
            name=sanitize_item_name(name),
            content=content.strip(),
            owner=owner,
            source_conv=source_conv,
            ts=ts or _now_iso(),
        )
        existing = self._read_category(category)
        replaced = any(cur.name == item.name for cur in existing)
        merged = [cur for cur in existing if cur.name != item.name] + [item]
        self._write_category(category, merged)
        self._revision += 1
        self.journal.append(
            "update" if replaced else "add",
            category=category,
            name=item.name,
            owner=owner,
            source_conv=source_conv,
        )
        return item

    def remove(self, category: str, name: str, *, owner: str | None = None) -> bool:
        validate_category(category)
        wanted = " ".join(name.split())
        existing = self._read_category(category)
        kept = [cur for cur in existing if cur.name != wanted]
        if len(kept) == len(existing):
            return False
        self._write_category(category, kept)
        self._revision += 1
        self.journal.append("remove", category=category, name=wanted, owner=owner)
        return True

    # ------------------------------------------------------------ internals

    def _category_path(self, category: str) -> Path:
        return self.root / f"{category}.md"

    def _read_category(self, category: str) -> list[MemoryItem]:
        path = self._category_path(category)
        if not path.exists():
            return []
        items: list[MemoryItem] = []
        name: str | None = None
        body: list[str] = []
        meta: dict[str, str] = {}

        def flush() -> None:
            nonlocal name, body, meta
            if name is not None:
                content = "\n".join(body).strip()
                items.append(
                    MemoryItem(
                        category=category,
                        name=name,
                        content=content,
                        owner=meta.get("owner"),
                        source_conv=meta.get("source"),
                        ts=meta.get("ts"),
                    )
                )
            name, body, meta = None, [], {}

        for line in path.read_text(encoding="utf-8").splitlines():
            heading = _ITEM_HEADING_RE.match(line)
            if heading:
                flush()
                name = " ".join(heading.group(1).split())
                continue
            if name is None:
                continue  # preamble (file title etc.) belongs to no item
            parsed = _parse_meta(line)
            if parsed is not None:
                meta = parsed
                continue
            body.append(line)
        flush()

        # Hand edits may duplicate a heading; last occurrence wins.
        deduped: dict[str, MemoryItem] = {item.name: item for item in items}
        return list(deduped.values())

    def _write_category(self, category: str, items: list[MemoryItem]) -> None:
        path = self._category_path(category)
        if not items:
            if path.exists():
                path.unlink()
            return
        parts: list[str] = [f"# {category}", ""]
        for item in items:
            parts.append(f"## {item.name}")
            parts.append("")
            parts.append(item.content)
            parts.append("")
            fields: list[str] = []
            if item.owner:
                fields.append(f"owner={_meta_value(item.owner)}")
            if item.source_conv:
                fields.append(f"source={_meta_value(item.source_conv)}")
            if item.ts:
                fields.append(f"ts={item.ts}")
            if fields:
                parts.append(f"<!-- wikimem: {' | '.join(fields)} -->")
                parts.append("")
        text = "\n".join(parts).rstrip("\n") + "\n"

        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
