"""Storage layer: one wiki RecallFile per topic (under ``wiki/``), ``##`` sections as items.

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

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ._serialize import atomic_write, now_iso, parse_meta, render_meta
from .journal import Journal
from .models import RecallItem

if TYPE_CHECKING:
    from .diary import Diary

# Store layout, not serialization format — keep out of `_serialize`.
JOURNAL_FILENAME = "journal.jsonl"
# Wiki RecallFiles live under this subdir (parallel to the diary's ``diary/``)
# so an unbounded, growing set of them never clutters the store root.
WIKI_DIRNAME = "wiki"

_FILE_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
_ITEM_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def validate_file(file: str) -> str:
    """RecallFile names are ASCII slugs: they double as filenames and link prefixes."""
    if not _FILE_RE.match(file):
        raise ValueError(
            f"invalid RecallFile name {file!r}: expected lowercase slug like 'daily_life'"
        )
    return file


def sanitize_item_name(name: str) -> str:
    """Item names may be any language, but must stay heading- and link-safe."""
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("item name is empty")
    if any(tok in cleaned for tok in ("[[", "]]", ":", "|", "#")):
        raise ValueError(f"item name {cleaned!r} contains reserved characters ([[ ]] : | #)")
    return cleaned


class MemoryStore:
    """Read/write access to a store's ``wiki/`` RecallFiles."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.journal = Journal(self.root / JOURNAL_FILENAME)
        # Bumped on every successful in-process write; lets derived state
        # (e.g. MemoryIndex) rebuild lazily. Out-of-band file edits are not
        # detected — rebuild the index explicitly after those.
        self._revision = 0
        self._diary: Diary | None = None

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def diary(self) -> Diary:
        """The event-stream primitive (ADR-0001), sharing this store's journal.

        Lazily constructed so ``import wikimem`` never pulls in the diary module
        unless a caller reaches for it. Diary writes land in the *same*
        ``journal.jsonl`` as wiki writes, but do not bump ``revision`` — the
        wiki BM25 index is not built over diary files.
        """
        if self._diary is None:
            from .diary import Diary

            self._diary = Diary(self.root, journal=self.journal)
        return self._diary

    # ---------------------------------------------------------------- reads

    def files(self) -> list[str]:
        wiki_dir = self.root / WIKI_DIRNAME
        if not wiki_dir.exists():
            return []
        return sorted(p.stem for p in wiki_dir.glob("*.md"))

    def items(self, file: str | None = None) -> list[RecallItem]:
        names = [file] if file is not None else self.files()
        out: list[RecallItem] = []
        for cat in names:
            out.extend(self._read_file(cat))
        return out

    def get(self, file: str, name: str) -> RecallItem | None:
        wanted = " ".join(name.split())
        for item in self._read_file(file):
            if item.name == wanted:
                return item
        return None

    # --------------------------------------------------------------- writes

    def add(
        self,
        file: str,
        name: str,
        content: str,
        *,
        owner: str | None = None,
        source_conv: str | None = None,
        ts: str | None = None,
    ) -> RecallItem:
        """Insert a new item, or replace the same-named item (update)."""
        validate_file(file)
        item = RecallItem(
            file=file,
            name=sanitize_item_name(name),
            content=content.strip(),
            owner=owner,
            source_conv=source_conv,
            ts=ts or now_iso(),
        )
        existing = self._read_file(file)
        replaced = any(cur.name == item.name for cur in existing)
        merged = [cur for cur in existing if cur.name != item.name] + [item]
        self._write_file(file, merged)
        self._revision += 1
        self.journal.append(
            "update" if replaced else "add",
            file=file,
            name=item.name,
            owner=owner,
            source_conv=source_conv,
        )
        return item

    def remove(self, file: str, name: str, *, owner: str | None = None) -> bool:
        validate_file(file)
        wanted = " ".join(name.split())
        existing = self._read_file(file)
        kept = [cur for cur in existing if cur.name != wanted]
        if len(kept) == len(existing):
            return False
        self._write_file(file, kept)
        self._revision += 1
        self.journal.append("remove", file=file, name=wanted, owner=owner)
        return True

    # ------------------------------------------------------------ internals

    def _file_path(self, file: str) -> Path:
        return self.root / WIKI_DIRNAME / f"{file}.md"

    def _read_file(self, file: str) -> list[RecallItem]:
        path = self._file_path(file)
        if not path.exists():
            return []
        items: list[RecallItem] = []
        name: str | None = None
        body: list[str] = []
        meta: dict[str, str] = {}

        def flush() -> None:
            nonlocal name, body, meta
            if name is not None:
                content = "\n".join(body).strip()
                items.append(
                    RecallItem(
                        file=file,
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
            parsed = parse_meta(line)
            if parsed is not None:
                meta = parsed
                continue
            body.append(line)
        flush()

        # Hand edits may duplicate a heading; last occurrence wins.
        deduped: dict[str, RecallItem] = {item.name: item for item in items}
        return list(deduped.values())

    def _write_file(self, file: str, items: list[RecallItem]) -> None:
        path = self._file_path(file)
        if not items:
            if path.exists():
                path.unlink()
            return
        parts: list[str] = [f"# {file}", ""]
        for item in items:
            parts.append(f"## {item.name}")
            parts.append("")
            parts.append(item.content)
            parts.append("")
            meta = render_meta(owner=item.owner, source_conv=item.source_conv, ts=item.ts)
            if meta:
                parts.append(meta)
                parts.append("")
        text = "\n".join(parts).rstrip("\n") + "\n"
        atomic_write(path, text)
