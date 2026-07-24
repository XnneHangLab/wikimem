"""Diary: the append-only event-stream primitive (ADR-0001).

Where the wiki (:class:`~wikimem.store.MemoryStore`) is the *state* layer —
"what is true now", items rewritten in place — the diary is the *event* layer:
"what happened, and when". The boundary is one line:

    Things that *happened* go in the diary; things that are *true now* go in
    the wiki.

Storage mirrors that split: one markdown file per day, ``diary/YYYY-MM-DD.md``;
one ``## HH:MM`` heading per event; the same ``<!-- wikimem: ... -->`` metadata
comment the wiki uses (shared via :mod:`wikimem._serialize`). The filename *is*
the time index — a date maps to a file in O(1), a range to a file set in
O(days), with no index structure. That is the ground ADR-0002's time gate will
stand on.

Two properties set it apart from the wiki:

* **Append-only.** The API only ever *adds* entries — there is no method to
  edit or delete one. (A human may still edit the file directly; the file is
  the truth. The day file is rewritten atomically on append to keep it in
  chronological order, but existing entries are preserved verbatim.)
* **A minute is not a key.** Two events can share ``## HH:MM``; a repeated
  heading is kept, not collapsed — the opposite of the wiki's last-one-wins
  dedup, because in an event stream both events are real.

The framework never generates or judges entry content — the vivid paragraph
(scene, feeling, and fact together) is written by the host's memorize step. It
may carry ``[[category:item]]`` wiki-links back into the state layer.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, tzinfo
from datetime import date as _date
from pathlib import Path

from ._serialize import atomic_write, parse_meta, render_meta
from .journal import Journal
from .models import DiaryEntry
from .store import JOURNAL_FILENAME

# Layout, not serialization format (see wikimem._serialize): the diary's own
# subdirectory under the store root, parallel to ``category/`` for wiki files.
DIARY_DIRNAME = "diary"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def _validate_date(date: str) -> str:
    """A diary date is a zero-padded, real calendar day ``YYYY-MM-DD``."""
    if not _DATE_RE.match(date):
        raise ValueError(f"invalid diary date {date!r}: expected YYYY-MM-DD")
    try:
        _date.fromisoformat(date)
    except ValueError as exc:  # e.g. 2026-13-40
        raise ValueError(f"invalid diary date {date!r}: {exc}") from exc
    return date


def _validate_time(time: str) -> str:
    """A diary time is a 24-hour wall clock ``HH:MM`` (00:00–23:59)."""
    if not _TIME_RE.match(time):
        raise ValueError(f"invalid diary time {time!r}: expected HH:MM (00:00-23:59)")
    return time


def _parse_iso(value: str) -> datetime:
    """ISO-8601 → aware datetime. Naive values are treated as UTC; bad input raises."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid diary ts {value!r}: expected ISO-8601") from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class Diary:
    """Append-only, day-partitioned event storage over plain markdown.

    Shares one ``journal.jsonl`` with the wiki: pass the store's journal so both
    primitives write the same log, or let it default to one at
    ``root / journal.jsonl``. Usually reached via ``MemoryStore.diary`` rather
    than constructed directly.
    """

    def __init__(self, root: Path | str, *, journal: Journal | None = None) -> None:
        self.root = Path(root)
        self._dir = self.root / DIARY_DIRNAME
        self.journal = journal if journal is not None else Journal(self.root / JOURNAL_FILENAME)

    # ---------------------------------------------------------------- writes

    def append(
        self,
        content: str,
        *,
        ts: str | None = None,
        date: str | None = None,
        time: str | None = None,
        owner: str | None = None,
        source_conv: str | None = None,
        tz: tzinfo | None = None,
    ) -> DiaryEntry:
        """Append one event to its day file and return the stored entry.

        The event's identity is three coordinates, all derivable from ``ts``:

        * ``ts`` — the precise instant (ISO-8601). Defaults to now, UTC.
        * ``date`` — ``YYYY-MM-DD``, which day file. Defaults to ``ts`` rendered
          in ``tz`` (the human's calendar day, local by default).
        * ``time`` — ``HH:MM`` heading. Defaults to ``ts`` rendered in ``tz``.

        A host that knows its own clock/timezone typically passes these
        explicitly; the defaults exist so the simple case just works. ``owner``
        and ``source_conv`` are optional provenance, stored in the same comment
        as wiki items. Raises ``ValueError`` on empty content or a malformed
        ``date`` / ``time``.
        """
        text = content.strip()
        if not text:
            raise ValueError("diary entry content is empty")

        if ts is not None:
            instant = _parse_iso(ts)
            # Always persist a normalized UTC instant so hand-set values cannot
            # leave non-ISO garbage (or mixed offsets) in the metadata comment.
            ts = instant.astimezone(UTC).isoformat(timespec="seconds")
        else:
            instant = datetime.now(UTC)
            ts = instant.isoformat(timespec="seconds")
        if date is None or time is None:
            local = instant.astimezone(tz)  # tz=None → system local zone
            date = date if date is not None else local.strftime("%Y-%m-%d")
            time = time if time is not None else local.strftime("%H:%M")
        date = _validate_date(date)
        time = _validate_time(time)

        entry = DiaryEntry(
            date=date,
            time=time,
            content=text,
            owner=owner,
            source_conv=source_conv,
            ts=ts,
        )
        day = self._read_day(date)
        day.append(entry)
        # Stable sort by wall-clock time: a late-arriving earlier event slots
        # into chronological order, and same-minute events keep insertion order.
        day.sort(key=lambda e: e.time)
        self._write_day(date, day)
        self.journal.append_diary(date=date, time=time, owner=owner, source_conv=source_conv)
        return entry

    # ----------------------------------------------------------------- reads

    def dates(self) -> list[str]:
        """Every day that has a file, ascending — ``YYYY-MM-DD`` strings.

        Lexical order equals chronological order for this format, so the list
        is already sorted by time.
        """
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.md") if _DATE_RE.match(p.stem))

    def day(self, date: str) -> list[DiaryEntry]:
        """All entries for one day, in file (chronological) order."""
        return self._read_day(_validate_date(date))

    def window(self, start: str, end: str) -> list[DiaryEntry]:
        """All entries in the inclusive date range ``[start, end]``, chronological.

        Bounds are ``YYYY-MM-DD``; a reversed pair is swapped. This is the
        O(days) file-set lookup ADR-0002's time gate stands on — the diary
        primitive offers only the window, no scoring.
        """
        start = _validate_date(start)
        end = _validate_date(end)
        if start > end:
            start, end = end, start
        out: list[DiaryEntry] = []
        for d in self.dates():  # ascending
            if d > end:
                break  # dates() is sorted, so nothing past `end` can still match
            if d >= start:
                out.extend(self._read_day(d))
        return out

    # ------------------------------------------------------------ internals

    def _day_path(self, date: str) -> Path:
        return self._dir / f"{date}.md"

    def _read_day(self, date: str) -> list[DiaryEntry]:
        path = self._day_path(date)
        if not path.exists():
            return []
        entries: list[DiaryEntry] = []
        time: str | None = None
        body: list[str] = []
        meta: dict[str, str] = {}

        def flush() -> None:
            nonlocal time, body, meta
            if time is not None:
                entries.append(
                    DiaryEntry(
                        date=date,
                        time=time,
                        content="\n".join(body).strip(),
                        owner=meta.get("owner"),
                        source_conv=meta.get("source"),
                        ts=meta.get("ts"),
                    )
                )
            time, body, meta = None, [], {}

        for line in path.read_text(encoding="utf-8").splitlines():
            heading = _HEADING_RE.match(line)
            if heading:
                flush()
                time = heading.group(1).strip()
                continue
            if time is None:
                continue  # the "# DATE" title / preamble belongs to no entry
            parsed = parse_meta(line)
            if parsed is not None:
                meta = parsed
                continue
            body.append(line)
        flush()
        # File order, and deliberately NOT deduped: append-only means a minute
        # may legitimately repeat, so every heading is its own entry.
        return entries

    def _write_day(self, date: str, entries: list[DiaryEntry]) -> None:
        path = self._day_path(date)
        if not entries:
            if path.exists():
                path.unlink()
            return
        parts: list[str] = [f"# {date}", ""]
        for entry in entries:
            parts.append(f"## {entry.time}")
            parts.append("")
            parts.append(entry.content)
            parts.append("")
            meta = render_meta(owner=entry.owner, source_conv=entry.source_conv, ts=entry.ts)
            if meta:
                parts.append(meta)
                parts.append("")
        text = "\n".join(parts).rstrip("\n") + "\n"
        atomic_write(path, text)
