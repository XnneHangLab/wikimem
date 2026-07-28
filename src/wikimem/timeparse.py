"""Regex fast path: turn a time expression in a query into a date window (ADR-0002).

Time is a **gate**, not a ranking signal — and a gate needs a range. This module
is the framework's floor for producing one: pure ``re`` + ``datetime``, no
``dateparser`` / ``arrow`` / ``TimeNLP``, because anything ``timedelta`` can
compute does not justify a dependency (hard constraint: zero infra).

The rule that shapes every pattern here is **narrow beats wrong**
(宁窄勿误): an expression is parsed only when it is unambiguous. Whatever is not
recognized returns ``None``, meaning *no time intent* — never a guess. A wrong
window silently hides the right memory, which is worse than no window at all,
because the caller then has no idea the search was filtered.

That leaves a clean division of labour: **regex is the framework's floor, an LLM
is the host's ceiling** (a host that recognizes "the day we argued" passes
``time_range=`` explicitly). There is deliberately no third parser in between.

Windows are inclusive ``(start, end)`` pairs of ``YYYY-MM-DD`` strings — the
same shape :meth:`wikimem.Diary.window` takes, since day files are the time index.
"""

from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime, timedelta, tzinfo

# A window is (start, end), inclusive, both YYYY-MM-DD.
TimeRange = tuple[str, str]

# Relative day offsets. Only expressions with one obvious meaning are listed;
# "the other day" / "recently" / 最近 are deliberately absent — they have no
# defensible boundary, and inventing one would filter away real memories.
_OFFSET_WORDS: dict[str, int] = {
    "前天": -2,
    "昨天": -1,
    "昨日": -1,
    "今天": 0,
    "today": 0,
    "yesterday": -1,
    "明天": 1,
    "后天": 2,
    "tomorrow": 1,
}

# 3天前 / 三天前 / 2 days ago …
_CN_DIGITS = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_DAYS_AGO_RE = re.compile(r"(\d+|[一两二三四五六七八九十])\s*天前")
_DAYS_AGO_EN_RE = re.compile(r"(\d+)\s+days?\s+ago", re.IGNORECASE)
_WEEKS_AGO_RE = re.compile(r"(\d+|[一两二三四五六七八九十])\s*(?:周|星期|礼拜)前")

# Absolute dates: 2026-07-21 / 2026/07/21 / 7月21日 / 7月21号
_ISO_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_CN_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")

# Whole named periods, anchored on the current week/month.
_LAST_WEEK_RE = re.compile(r"上(?:个|一)?(?:周|星期|礼拜)")
_THIS_WEEK_RE = re.compile(r"(?:这|本)(?:个|一)?(?:周|星期|礼拜)")
_LAST_MONTH_RE = re.compile(r"上(?:个)?月")
_THIS_MONTH_RE = re.compile(r"(?:这|本)(?:个)?月")

# 上周三 / 这周五 — a specific weekday inside the previous/current week.
_WEEKDAYS: dict[str, int] = {  # Monday = 0, matching date.weekday()
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_WEEKDAY_RE = re.compile(r"(上|这|本)(?:个|一)?(?:周|星期|礼拜)\s*([一二三四五六日天])")


def _today(tz: tzinfo | None) -> _date:
    """The caller's *local* calendar day — diary files are named by local date."""
    return datetime.now(tz).date()


def _iso(day: _date) -> str:
    return day.isoformat()


def _day(day: _date) -> TimeRange:
    """A single day as a window."""
    return _iso(day), _iso(day)


def _int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _CN_DIGITS.get(token)


def parse_time_range(
    text: str, *, tz: tzinfo | None = None, today: _date | None = None
) -> TimeRange | None:
    """Parse a time expression out of ``text``; ``None`` when there is none.

    ``tz`` selects the calendar the relative expressions are resolved against
    (default: system local, matching how diary day files are named). ``today``
    overrides "now" outright — used by tests, and by a host that wants windows
    resolved against a fixed clock.

    Returns an inclusive ``(start, end)`` of ``YYYY-MM-DD``, ready for
    :meth:`wikimem.Diary.window`. Recognizing nothing is a normal, frequent
    outcome: most queries carry no time intent at all.
    """
    if not text:
        return None
    now = today if today is not None else _today(tz)

    # Absolute dates first: they are the most specific reading available.
    m = _ISO_DATE_RE.search(text)
    if m:
        try:
            return _day(_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return None  # 2026-13-40 — a date-shaped string that is not a date

    m = _CN_MONTH_DAY_RE.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            candidate = _date(now.year, month, day)
        except ValueError:
            return None
        # A bare 月/日 has no year; assume the most recent occurrence, since a
        # diary is asked about the past far more often than the future.
        if candidate > now:
            try:
                candidate = _date(now.year - 1, month, day)
            except ValueError:
                return None
        return _day(candidate)

    # 上周三 / 这周五 — must precede the whole-week patterns, which also match.
    m = _WEEKDAY_RE.search(text)
    if m:
        monday = now - timedelta(days=now.weekday())
        if m.group(1) == "上":
            monday -= timedelta(days=7)
        return _day(monday + timedelta(days=_WEEKDAYS[m.group(2)]))

    # N 天前 / N days ago / N 周前
    for pattern in (_DAYS_AGO_RE, _DAYS_AGO_EN_RE):
        m = pattern.search(text)
        if m:
            n = _int(m.group(1))
            return _day(now - timedelta(days=n)) if n is not None else None

    m = _WEEKS_AGO_RE.search(text)
    if m:
        n = _int(m.group(1))
        if n is None:
            return None
        monday = now - timedelta(days=now.weekday() + 7 * n)
        return _iso(monday), _iso(monday + timedelta(days=6))

    # Whole weeks / months.
    if _LAST_WEEK_RE.search(text):
        monday = now - timedelta(days=now.weekday() + 7)
        return _iso(monday), _iso(monday + timedelta(days=6))
    if _THIS_WEEK_RE.search(text):
        monday = now - timedelta(days=now.weekday())
        return _iso(monday), _iso(monday + timedelta(days=6))
    if _LAST_MONTH_RE.search(text):
        first_this = now.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return _iso(last_prev.replace(day=1)), _iso(last_prev)
    if _THIS_MONTH_RE.search(text):
        first = now.replace(day=1)
        next_first = (first + timedelta(days=32)).replace(day=1)
        return _iso(first), _iso(next_first - timedelta(days=1))

    # Single-word day offsets last, so the more specific readings above always
    # win. ASCII words need word boundaries ("today" must not fire inside
    # "todays_plan"); CJK has no boundaries, and these words are unambiguous.
    lowered = text.lower()
    for word, offset in _OFFSET_WORDS.items():
        hit = re.search(rf"\b{word}\b", lowered) is not None if word.isascii() else word in text
        if hit:
            return _day(now + timedelta(days=offset))

    return None
