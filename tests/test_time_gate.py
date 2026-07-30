"""Time gate — diary becomes retrievable (ADR-0002, Phase 2).

The point of these: a window **filters candidates**, it never votes. So the
things worth pinning are that diary entries reach the ranking at all, that wiki
keeps competing unfiltered (§7), that no window means no behaviour change, and
that an empty window relaxes instead of answering "I don't remember" (§4).
"""

from datetime import date
from pathlib import Path

import pytest

from wikimem import MemoryIndex, MemoryStore

TODAY = date(2026, 7, 24)  # Friday


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    s = MemoryStore(tmp_path / "memory")
    # wiki: standing facts
    s.add("preferences", "likes-the-sea", "喜欢海边，提到过想去海边玩。")
    s.add("work", "current-job", "在一家做机器人的公司上班。")
    # diary: events on three different days
    s.diary.append("晚饭吃了拉面，汤头很浓。", date="2026-07-22", time="19:30")
    s.diary.append("下午去了海边，风很大。", date="2026-07-22", time="15:00")
    s.diary.append("今天吃了寿司。", date="2026-07-23", time="19:00")
    s.diary.append("他说换了工作，语气很兴奋。", date="2026-07-24", time="14:30")
    return s


def names(result) -> list[str]:
    return [e.item.name for e in result.items]


def files(result) -> set[str]:
    return {e.item.file for e in result.items}


# ------------------------------------------------------- the motivating query


def test_diary_is_retrievable_within_a_window(store: MemoryStore):
    """前天晚上我吃了什么 — the question the diary was built to answer."""
    index = MemoryIndex(store)
    result = index.retrieve("前天晚上吃了什么", tz=None, time_range=("2026-07-22", "2026-07-22"))

    assert result.time_range == ("2026-07-22", "2026-07-22")
    assert result.time_range_source == "explicit"
    assert any("拉面" in e.item.content for e in result.items)


def test_window_parsed_from_the_query_itself(store: MemoryStore):
    index = MemoryIndex(store)
    # No explicit range: the regex fast path finds "前天" (relative to TODAY).
    result = index.retrieve("前天吃了什么", time_range=None, tz=None)
    # Resolved against the real clock, so just assert the plumbing, not the date:
    parsed = index.retrieve("前天吃了什么")
    assert parsed.time_range_source in (None, "parsed")
    assert result.time_range_source == parsed.time_range_source


def test_out_of_window_diary_entries_are_excluded(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("吃了什么", time_range=("2026-07-22", "2026-07-22"))

    contents = " ".join(e.item.content for e in result.items)
    assert "拉面" in contents  # in window
    assert "寿司" not in contents  # 07-23, outside the window — wrong, not merely less relevant


# ------------------------------------------------------- wiki keeps competing


def test_wiki_is_not_filtered_by_the_window(store: MemoryStore):
    """§7: the timeline belongs to the diary; wiki items are never time-gated."""
    index = MemoryIndex(store)
    result = index.retrieve("海边", time_range=("2026-07-22", "2026-07-22"))

    # both layers can surface together: the event and the standing preference
    assert "2026-07-22" in files(result)  # the diary day file
    assert "preferences" in files(result)


def test_wiki_only_query_still_works_with_a_window(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("机器人公司", time_range=("2026-07-22", "2026-07-22"))
    assert "current-job" in names(result)


# ------------------------------------------------------- no window = no change


def test_no_window_leaves_diary_out_and_behaviour_unchanged(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("吃了什么")  # no time expression anywhere

    assert result.time_range is None
    assert result.time_range_source is None
    assert "diary" not in files(result)  # diary only enters through a window


def test_unparseable_time_words_do_not_open_a_window(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("最近吃了什么")  # 宁窄勿误: no defensible boundary
    assert result.time_range is None


# ------------------------------------------------------------ degenerate case


def test_empty_query_with_window_returns_the_window_newest_first(store: MemoryStore):
    """§3: time works alone — 'recall that day' without time ever scoring."""
    index = MemoryIndex(store)
    result = index.retrieve("", time_range=("2026-07-22", "2026-07-23"))

    # newest first, ordered by (day, time) — a diary item's name is only ``HH:MM``,
    # so sorting on the name alone would interleave the two days.
    assert [(e.item.file, e.item.name) for e in result.items] == [
        ("2026-07-23", "19:00"),
        ("2026-07-22", "19:30"),
        ("2026-07-22", "15:00"),
    ]
    assert files(result) == {"2026-07-22", "2026-07-23"}


def test_empty_query_without_window_still_returns_nothing(store: MemoryStore):
    assert MemoryIndex(store).retrieve("").items == []


# ------------------------------------------------------------------ widening


def test_empty_window_is_widened_rather_than_answered_empty(store: MemoryStore):
    """§4: relax instead of "I don't remember" — 07-21 is empty, 07-22 is not."""
    index = MemoryIndex(store)
    result = index.retrieve("", time_range=("2026-07-21", "2026-07-21"))

    assert result.time_range_widened is True
    assert result.time_range == ("2026-07-20", "2026-07-22")
    assert any("拉面" in e.item.content for e in result.items)


def test_a_window_with_entries_is_not_widened(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("", time_range=("2026-07-22", "2026-07-22"))
    assert result.time_range_widened is False
    assert result.time_range == ("2026-07-22", "2026-07-22")


def test_still_empty_after_widening_returns_empty(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("", time_range=("2020-01-01", "2020-01-01"))
    assert result.items == []


# --------------------------------------------------------------- integration


def test_diary_hit_expands_its_wiki_link(tmp_path: Path):
    """A link written inside a diary entry still resolves into the wiki."""
    s = MemoryStore(tmp_path / "memory")
    s.add("work", "current-job", "在一家做机器人的公司上班。")
    s.diary.append("他说换了工作。[[work:current-job]]", date="2026-07-24", time="14:30")

    result = MemoryIndex(s).retrieve("换了工作", time_range=("2026-07-24", "2026-07-24"))
    assert "current-job" in names(result)
    assert any(e.source == "link" for e in result.items)


def test_budget_applies_across_both_layers(store: MemoryStore):
    index = MemoryIndex(store)
    result = index.retrieve("海边", time_range=("2026-07-22", "2026-07-22"), budget_tokens=12)
    assert result.budget_used <= 12 or len(result.items) == 1  # first entry always kept


def test_diary_entry_carries_its_provenance(tmp_path: Path):
    s = MemoryStore(tmp_path / "memory")
    s.diary.append("去了海边。", date="2026-07-24", time="09:00", owner="user:xnne")
    (hit,) = MemoryIndex(s).retrieve("海边", time_range=("2026-07-24", "2026-07-24")).items
    # the day file IS the RecallFile; the HH:MM heading IS the item name
    assert hit.item.file == "2026-07-24"
    assert hit.item.name == "09:00"
    assert hit.item.owner == "user:xnne"
    assert hit.item.ts is not None


def test_reversed_explicit_window_is_normalized(store: MemoryStore):
    """A reversed pair is swapped at the boundary, once.

    ``Diary.window`` tolerates one on its own, so results were already correct —
    but an un-normalized pair reports backwards in ``explain`` and makes the
    widen fallback *shrink* the window instead of growing it.
    """
    index = MemoryIndex(store)
    result = index.retrieve("拉面", time_range=("2026-07-23", "2026-07-21"))
    assert result.time_range == ("2026-07-21", "2026-07-23")


def test_reversed_empty_window_still_widens_outward(store: MemoryStore):
    # Reversed 07-21..07-20 normalizes to 07-20..07-21, which is empty, so the
    # fallback must reach *outward* to 07-19..07-22 and pick up the 07-22
    # entries. Un-normalized, _widen would have yielded 07-20..07-21 — an
    # inward collapse that stays empty, silently skipping the fallback.
    index = MemoryIndex(store)
    result = index.retrieve("", time_range=("2026-07-21", "2026-07-20"))
    assert result.time_range_widened is True
    assert result.time_range == ("2026-07-19", "2026-07-22")
    assert result.items  # the 07-22 entries are reachable again
