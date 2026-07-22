"""Core data types.

An item is the retrieval unit (L2 in the resource/category/item layering):
one ``##`` section inside a category markdown file, carrying free-text
content, optional provenance metadata, and in-content wiki-links.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WikiLink:
    """An in-content cross-category reference: ``[[category:item-name]]``."""

    category: str
    name: str

    def render(self) -> str:
        return f"[[{self.category}:{self.name}]]"


@dataclass
class MemoryItem:
    """One memory entry inside a category file.

    ``ts`` is an ISO-8601 UTC timestamp string. ``owner`` / ``source_conv`` /
    ``ts`` are ``None`` for items that were hand-written into the file without
    a metadata comment — tolerated by design: the files are user-editable.
    """

    category: str
    name: str
    content: str
    owner: str | None = None
    source_conv: str | None = None
    ts: str | None = None

    @property
    def links(self) -> list[WikiLink]:
        from .links import parse_wiki_links

        return parse_wiki_links(self.content)


@dataclass
class DiaryEntry:
    """One event in the diary (ADR-0001): the *event-stream* primitive.

    Where a :class:`MemoryItem` is state ("what is true now", rewritten in
    place), a diary entry is an event ("what happened, and when"). It lives at
    ``## HH:MM`` inside a per-day file ``diary/YYYY-MM-DD.md``; ``date`` and
    ``time`` are that file's name and that heading, kept as strings because
    they *are* the on-disk address. ``ts`` is the precise UTC instant
    (ISO-8601), the machine-sortable truth behind the human-local ``time``.

    Diary is append-only: entries are only ever added, never edited through the
    API. Two events may share a minute, so — unlike wiki headings — a repeated
    ``## HH:MM`` is *not* a duplicate to collapse; both are kept.
    """

    date: str  # YYYY-MM-DD — the day file
    time: str  # HH:MM — the heading (human-local wall clock)
    content: str
    owner: str | None = None
    source_conv: str | None = None
    ts: str | None = None  # ISO-8601 UTC instant

    @property
    def links(self) -> list[WikiLink]:
        from .links import parse_wiki_links

        return parse_wiki_links(self.content)
