"""Wiki-link parsing: ``[[category:item-name]]`` inside item content.

Parsing is deliberately liberal (hand-edited files must not crash reads);
writing goes through :func:`wikimem.store.validate_category` /
``sanitize_item_name`` which are strict.
"""

from __future__ import annotations

import re

from .models import WikiLink

# category = anything up to the FIRST colon, no brackets/newlines;
# name = the rest, no brackets/newlines. Item names may contain colons? No —
# keeping names colon-free keeps links unambiguous and greppable.
_LINK_RE = re.compile(r"\[\[([^\[\]\n:]+):([^\[\]\n:]+)\]\]")


def parse_wiki_links(text: str) -> list[WikiLink]:
    """Extract wiki-links in order of appearance. Malformed links are ignored."""
    return [
        WikiLink(category.strip(), name.strip())
        for category, name in _LINK_RE.findall(text)
        if category.strip() and name.strip()
    ]
