"""Regex fast path — query text to a date window (ADR-0002, Phase 1).

Every case pins ``today=2026-07-24`` (a **Friday**, so week maths is visible)
rather than the real clock, so the table is deterministic. The other half of the
table is just as important as the hits: expressions we refuse to guess at must
keep returning ``None`` (宁窄勿误).
"""

from datetime import date, timedelta, timezone

import pytest

from wikimem import parse_time_range

FRI = date(2026, 7, 24)  # anchor: Friday; that week's Monday is 2026-07-20


def parse(text: str, **kw):
    return parse_time_range(text, today=FRI, **kw)


# --------------------------------------------------------------- single days


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今天吃了什么", "2026-07-24"),
        ("昨天晚上我吃了什么", "2026-07-23"),
        ("昨日的事", "2026-07-23"),
        ("前天晚上我吃了什么", "2026-07-22"),  # the question the diary exists for
        ("明天要做什么", "2026-07-25"),
        ("后天呢", "2026-07-26"),
        ("what did I do yesterday", "2026-07-23"),
        ("anything today?", "2026-07-24"),
        ("3天前发生了什么", "2026-07-21"),
        ("三天前呢", "2026-07-21"),  # CJK numeral
        ("两天前", "2026-07-22"),
        ("十天前", "2026-07-14"),
        ("2 days ago", "2026-07-22"),
        ("10 days ago", "2026-07-14"),
    ],
)
def test_single_day_expressions(text: str, expected: str):
    assert parse(text) == (expected, expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-07-21 那天", "2026-07-21"),
        ("2026/07/21", "2026-07-21"),
        ("2026-7-1 的记录", "2026-07-01"),
        ("7月21日我们聊了什么", "2026-07-21"),
        ("7月21号", "2026-07-21"),
        ("12月25号", "2025-12-25"),  # future in this year -> most recent past
    ],
)
def test_absolute_dates(text: str, expected: str):
    assert parse(text) == (expected, expected)


# ------------------------------------------------------------------- weekdays


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("这周一", "2026-07-20"),
        ("本周三", "2026-07-22"),
        ("这周五做了什么", "2026-07-24"),
        ("上周三", "2026-07-15"),
        ("上周日", "2026-07-19"),
        ("上礼拜二", "2026-07-14"),
    ],
)
def test_weekday_within_week(text: str, expected: str):
    assert parse(text) == (expected, expected)


# ---------------------------------------------------------------- whole spans


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("这周", ("2026-07-20", "2026-07-26")),
        ("本星期发生的事", ("2026-07-20", "2026-07-26")),
        ("上周", ("2026-07-13", "2026-07-19")),
        ("上个星期", ("2026-07-13", "2026-07-19")),
        ("两周前", ("2026-07-06", "2026-07-12")),
        ("这个月", ("2026-07-01", "2026-07-31")),
        ("上个月", ("2026-06-01", "2026-06-30")),
    ],
)
def test_whole_week_and_month(text: str, expected: tuple[str, str]):
    assert parse(text) == expected


def test_last_month_across_year_boundary():
    assert parse_time_range("上个月", today=date(2026, 1, 15)) == ("2025-12-01", "2025-12-31")


# ------------------------------------------------- narrow beats wrong (None)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "我喜欢海边",  # no time intent at all
        "最近怎么样",  # vague on purpose: no defensible boundary
        "前几天",  # ditto
        "以前的事",
        "过一会儿",
        "2026-13-40",  # date-shaped, not a date
        "13月45号",
    ],
)
def test_unparseable_returns_none(text: str):
    assert parse(text) is None


def test_ascii_words_need_boundaries():
    # "today" glued into a longer token must not trigger a window …
    assert parse("todays_plan.md") is None
    assert parse("yesterdays") is None
    # … but a real word boundary counts, even against punctuation.
    assert parse("later today-ish") == ("2026-07-24", "2026-07-24")


# ----------------------------------------------------------------- precedence


def test_specific_reading_wins_over_generic():
    # "上周三" is a weekday, not the whole of last week.
    assert parse("上周三") == ("2026-07-15", "2026-07-15")
    # An explicit date beats a relative word appearing later in the sentence.
    assert parse("2026-07-01 那天，比昨天更早") == ("2026-07-01", "2026-07-01")


# ----------------------------------------------------------------- time zones


def test_tz_selects_the_local_calendar_day():
    # Without `today`, "今天" resolves against the caller's zone. Around the date
    # line the two zones legitimately differ by a day.
    east = parse_time_range("今天", tz=timezone(timedelta(hours=14)))
    west = parse_time_range("今天", tz=timezone(timedelta(hours=-11)))
    assert east is not None and west is not None
    assert date.fromisoformat(east[0]) - date.fromisoformat(west[0]) in (
        timedelta(0),
        timedelta(days=1),
    )


def test_window_is_inclusive_and_ordered():
    for text in ("上周", "这个月", "两周前", "昨天"):
        got = parse(text)
        assert got is not None
        assert got[0] <= got[1]
