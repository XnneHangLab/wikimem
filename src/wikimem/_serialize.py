"""Shared on-disk serialization: the metadata comment and atomic writes.

The wiki storage layer (``category/*.md``) encodes provenance in an HTML comment
and persists via a temp-file-plus-``os.replace``. Both pieces are pulled out
here so there is exactly one parser and one renderer for the on-disk format —
the seam the diary primitive (ADR-0001) reuses verbatim rather than reimplement,
so the two formats cannot drift apart.

Path constants (e.g. journal filename, diary directory) do **not** belong here —
those are store layout, not serialization format.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_META_RE = re.compile(r"^<!--\s*wikimem:\s*(.*?)\s*-->\s*$")


def now_iso() -> str:
    """Current instant as an ISO-8601 UTC string, second precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_meta(line: str) -> dict[str, str] | None:
    """Parse a metadata comment line, or ``None`` if it isn't one.

    Tolerant by design (hand edits must never crash a read): a line that does
    not match the comment shape is simply not metadata, and malformed inner
    fields are dropped rather than raised.
    """
    m = _META_RE.match(line.strip())
    if not m:
        return None
    fields: dict[str, str] = {}
    for part in m.group(1).split("|"):
        key, _, value = part.strip().partition("=")
        if key and value:
            fields[key.strip()] = value.strip()
    return fields


def meta_value(value: str) -> str:
    """Escape a value for the comment: ``|`` is the field separator."""
    return value.replace("|", "/").strip()


def render_meta(
    *,
    owner: str | None = None,
    source_conv: str | None = None,
    ts: str | None = None,
) -> str | None:
    """Render the metadata comment, or ``None`` when no field is set.

    ``owner`` / ``source`` / ``ts`` all go through ``meta_value`` so a hand-set
    or adversarial value with ``|`` cannot split fields. Empty / whitespace-only
    strings are treated as unset (same as ``None``).
    """
    fields: list[str] = []
    if owner and (owner_v := meta_value(owner)):
        fields.append(f"owner={owner_v}")
    if source_conv and (source_v := meta_value(source_conv)):
        fields.append(f"source={source_v}")
    if ts and (ts_v := meta_value(ts)):
        fields.append(f"ts={ts_v}")
    if not fields:
        return None
    return f"<!-- wikimem: {' | '.join(fields)} -->"


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a same-directory temp file + ``os.replace``.

    The temp file shares ``path``'s directory so the replace is atomic (same
    filesystem), and is cleaned up on any failure so a crash never leaves a
    ``.tmp`` behind. ``path.parent`` is created if missing, so nested layouts
    (e.g. ``diary/YYYY-MM-DD.md``) work without a separate mkdir.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
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
