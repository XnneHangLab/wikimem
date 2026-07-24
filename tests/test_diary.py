"""Diary storage — the append-only event-stream primitive (ADR-0001).

Covers the decisions the ADR flagged for implementation time: append-only with
no edit/delete, same-minute entries kept (not deduped like wiki), chronological
day files, UTC ``ts`` vs local file date, one shared journal with the wiki, and
the inclusive multi-day ``window()`` range read.
"""

from datetime import timedelta, timezone
from pathlib import Path

import pytest

from wikimem import Diary, MemoryStore


@pytest.fixture()
def diary(tmp_path: Path) -> Diary:
    return Diary(tmp_path / "memory")


# ------------------------------------------------------------------ roundtrip


def test_append_and_read_roundtrip(diary: Diary):
    entry = diary.append(
        "今天他说换了工作，语气很兴奋。[[work:current-job]]",
        date="2026-07-21",
        time="14:30",
        owner="user:xnne",
        source_conv="conv_20260721",
    )
    assert entry.date == "2026-07-21"
    assert entry.time == "14:30"

    (read,) = diary.day("2026-07-21")
    assert read.content == "今天他说换了工作，语气很兴奋。[[work:current-job]]"
    assert read.owner == "user:xnne"
    assert read.source_conv == "conv_20260721"
    assert read.ts  # stamped automatically
    assert [link.category for link in read.links] == ["work"]


def test_file_is_human_readable_markdown(diary: Diary, tmp_path: Path):
    diary.append("去了海边。", date="2026-07-21", time="14:30", owner="user:xnne")
    text = (tmp_path / "memory" / "diary" / "2026-07-21.md").read_text(encoding="utf-8")
    assert text.startswith("# 2026-07-21\n")
    assert "## 14:30" in text
    assert "<!-- wikimem: owner=user:xnne" in text


def test_empty_day_and_dates_are_empty(diary: Diary):
    assert diary.day("2026-07-21") == []
    assert diary.dates() == []


# ------------------------------------------------- append-only, minute-is-not-a-key


def test_append_only_preserves_earlier_entries(diary: Diary):
    diary.append("第一条", date="2026-07-21", time="09:00")
    diary.append("第二条", date="2026-07-21", time="10:00")
    assert [e.content for e in diary.day("2026-07-21")] == ["第一条", "第二条"]


def test_same_minute_entries_are_both_kept(diary: Diary, tmp_path: Path):
    # The opposite of the wiki's last-one-wins: two events can share a minute.
    diary.append("先吃了饭。", date="2026-07-21", time="14:30")
    diary.append("然后散步。", date="2026-07-21", time="14:30")

    entries = diary.day("2026-07-21")
    assert [e.content for e in entries] == ["先吃了饭。", "然后散步。"]
    assert all(e.time == "14:30" for e in entries)

    text = (tmp_path / "memory" / "diary" / "2026-07-21.md").read_text(encoding="utf-8")
    assert text.count("## 14:30") == 2


def test_entries_sorted_chronologically_within_day(diary: Diary):
    diary.append("晚上", date="2026-07-21", time="22:10")
    diary.append("早上", date="2026-07-21", time="07:05")
    diary.append("下午", date="2026-07-21", time="15:00")
    assert [e.time for e in diary.day("2026-07-21")] == ["07:05", "15:00", "22:10"]


def test_dates_lists_day_files_ascending(diary: Diary):
    diary.append("x", date="2026-07-22", time="10:00")
    diary.append("y", date="2026-07-20", time="10:00")
    assert diary.dates() == ["2026-07-20", "2026-07-22"]


# ----------------------------------------------------------------------- window


def test_window_is_inclusive_and_chronological(diary: Diary):
    diary.append("d1", date="2026-07-20", time="10:00")
    diary.append("d2 morning", date="2026-07-21", time="08:00")
    diary.append("d2 night", date="2026-07-21", time="20:00")
    diary.append("d3", date="2026-07-22", time="10:00")

    got = diary.window("2026-07-21", "2026-07-22")
    assert [e.content for e in got] == ["d2 morning", "d2 night", "d3"]


def test_window_reversed_bounds_are_swapped(diary: Diary):
    diary.append("a", date="2026-07-20", time="10:00")
    diary.append("b", date="2026-07-21", time="10:00")
    assert [e.date for e in diary.window("2026-07-21", "2026-07-20")] == [
        "2026-07-20",
        "2026-07-21",
    ]


def test_window_single_day_empty_range_and_validation(diary: Diary):
    diary.append("only", date="2026-07-21", time="09:00")
    assert [e.content for e in diary.window("2026-07-21", "2026-07-21")] == ["only"]
    assert diary.window("2026-08-01", "2026-08-31") == []
    with pytest.raises(ValueError):
        diary.window("not-a-date", "2026-07-21")
    with pytest.raises(ValueError):
        diary.window("2026-07-21", "not-a-date")


# -------------------------------------------------------------- time semantics


def test_explicit_ts_is_stored_verbatim(diary: Diary):
    diary.append("x", date="2026-07-21", time="14:30", ts="2026-07-21T06:30:00+00:00")
    (entry,) = diary.day("2026-07-21")
    assert entry.ts == "2026-07-21T06:30:00+00:00"


def test_explicit_ts_is_normalized_to_utc_seconds(diary: Diary):
    # Offset form is accepted, but the on-disk metadata always stores UTC seconds.
    diary.append("x", date="2026-07-21", time="14:30", ts="2026-07-21T14:30:00+08:00")
    (entry,) = diary.day("2026-07-21")
    assert entry.ts == "2026-07-21T06:30:00+00:00"


def test_defaults_derive_date_and_time_from_ts_in_tz(diary: Diary):
    # 23:30 UTC is 07:30 the next day in +08:00 — the file lands on the local day.
    diary.append("跨日", ts="2026-07-21T23:30:00+00:00", tz=timezone(timedelta(hours=8)))
    (entry,) = diary.day("2026-07-22")
    assert entry.time == "07:30"
    assert entry.ts == "2026-07-21T23:30:00+00:00"


def test_default_ts_is_utc(diary: Diary):
    entry = diary.append("现在", date="2026-07-21", time="10:00")
    assert entry.ts is not None and entry.ts.endswith("+00:00")


# ------------------------------------------------------------------ tolerance


def test_hand_edited_day_without_metadata_is_tolerated(diary: Diary, tmp_path: Path):
    d = tmp_path / "memory" / "diary"
    d.mkdir(parents=True)
    (d / "2026-07-21.md").write_text(
        "# 2026-07-21\n\n## 09:00\n\n手写的日记，没有元数据注释。\n",
        encoding="utf-8",
    )
    (entry,) = diary.day("2026-07-21")
    assert entry.owner is None and entry.ts is None
    assert entry.time == "09:00"
    assert "手写" in entry.content


# ------------------------------------------------------------------ validation


def test_validation_rejects_bad_input(diary: Diary):
    with pytest.raises(ValueError):
        diary.append("", date="2026-07-21", time="14:30")  # empty content
    with pytest.raises(ValueError):
        diary.append("x", date="2026-7-21", time="14:30")  # not zero-padded
    with pytest.raises(ValueError):
        diary.append("x", date="2026-13-01", time="14:30")  # impossible month
    with pytest.raises(ValueError):
        diary.append("x", date="2026-07-21", time="24:00")  # hour out of range
    with pytest.raises(ValueError):
        diary.append("x", date="2026-07-21", time="9:00")  # not HH:MM
    with pytest.raises(ValueError):
        diary.append("x", date="2026-07-21", time="14:30", ts="not-a-ts")
    with pytest.raises(ValueError):
        diary.day("not-a-date")


# ------------------------------------------------------- store integration


def test_diary_append_is_journaled(diary: Diary):
    diary.append("事件", date="2026-07-21", time="14:30", owner="user:xnne", source_conv="c1")
    (entry,) = diary.journal.entries()
    assert entry["action"] == "diary"
    assert entry["date"] == "2026-07-21"
    assert entry["time"] == "14:30"
    assert entry["owner"] == "user:xnne"
    assert entry["source_conv"] == "c1"
    assert entry["ts"]


def test_store_diary_shares_one_journal(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory")
    store.add("preferences", "likes-the-sea", "x")
    store.diary.append("去了海边。", date="2026-07-21", time="14:30")
    assert [e["action"] for e in store.journal.entries()] == ["add", "diary"]


def test_diary_files_are_not_wiki_categories(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory")
    store.add("preferences", "a", "x")
    store.diary.append("事件", date="2026-07-21", time="09:00")
    # diary lives in the diary/ subdir, so it never shows up as a category.
    assert store.categories() == ["preferences"]
    assert [item.name for item in store.items()] == ["a"]


def test_store_diary_is_cached(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory")
    assert store.diary is store.diary


def test_diary_write_does_not_bump_store_revision(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory")
    before = store.revision
    store.diary.append("事件", date="2026-07-21", time="09:00")
    assert store.revision == before  # wiki BM25 index is not built over diary
