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
