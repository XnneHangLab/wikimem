import pytest

from wikimem import MemoryIndex, MemoryStore


@pytest.fixture()
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory")
    s.add(
        "preferences",
        "likes-the-sea",
        "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
        owner="user:xnne",
    )
    s.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")
    s.add("reading", "sci-fi-taste", "喜欢科幻小说，最近在读三体。[[preferences:likes-the-sea]]")
    s.add("preferences", "coffee", "只喝手冲咖啡，不加糖。")
    return s


@pytest.fixture()
def index(store):
    return MemoryIndex(store, use_jieba=False)


def test_relevant_item_ranks_first(index):
    result = index.retrieve("想去海边玩")
    assert result.items, "expected at least one hit"
    top = result.items[0]
    assert top.item.name == "likes-the-sea"
    assert top.source == "hit"
    assert top.score and top.score > 0
    assert "海边" in top.matched_terms


def test_irrelevant_items_excluded(index):
    names = [r.item.name for r in index.retrieve("想去海边玩").items]
    assert "coffee" not in names


def test_one_hop_link_expansion(index):
    result = index.retrieve("想去海边玩")
    by_name = {r.item.name: r for r in result.items}
    assert "beach-trip-plan" in by_name
    linked = by_name["beach-trip-plan"]
    assert linked.source == "link"
    assert linked.via == "likes-the-sea"


def test_expansion_is_exactly_one_hop(store):
    # sci-fi-taste links to likes-the-sea, which links to beach-trip-plan.
    # A query hitting only sci-fi-taste must pull likes-the-sea but NOT
    # transitively beach-trip-plan.
    index = MemoryIndex(store, use_jieba=False)
    result = index.retrieve("科幻小说三体")
    names = [r.item.name for r in result.items]
    assert "sci-fi-taste" in names
    assert "likes-the-sea" in names
    assert "beach-trip-plan" not in names


def test_no_duplicate_items_in_sequence(index):
    result = index.retrieve("喜欢海边 科幻")
    names = [r.item.name for r in result.items]
    assert len(names) == len(set(names))


def test_expand_links_can_be_disabled(index):
    result = index.retrieve("想去海边玩", expand_links=False)
    assert all(r.source == "hit" for r in result.items)


def test_unresolved_link_is_reported(store):
    store.add("notes", "dangling", "提到海边和 [[nowhere:missing-item]]。")
    index = MemoryIndex(store, use_jieba=False)
    result = index.retrieve("海边")
    assert "[[nowhere:missing-item]]" in result.unresolved_links


def test_budget_prefix_cut(index):
    full = index.retrieve("想去海边玩")
    assert len(full.items) >= 2
    tight = index.retrieve("想去海边玩", budget_tokens=full.items[0].tokens_est, explain=True)
    assert len(tight.items) == 1
    assert tight.dropped, "explain should surface what the budget cut"
    assert tight.budget_used <= full.items[0].tokens_est


def test_first_item_kept_even_over_budget(index):
    result = index.retrieve("想去海边玩", budget_tokens=1)
    assert len(result.items) == 1


def test_index_rebuilds_after_store_write(store, index):
    assert index.retrieve("手冲咖啡").items  # builds the index
    store.add("preferences", "tea", "也喝乌龙茶。")
    names = [r.item.name for r in index.retrieve("乌龙茶").items]
    assert "tea" in names


def test_empty_query_and_empty_store(tmp_path, index):
    assert index.retrieve("").items == []
    empty = MemoryIndex(MemoryStore(tmp_path / "empty"), use_jieba=False)
    assert empty.retrieve("海边").items == []


def test_zero_llm_calls_is_structural():
    # The retrieval module must not import any LLM/network machinery.
    from wikimem import retrieval

    with open(retrieval.__file__, encoding="utf-8") as f:
        source = f.read()
    for forbidden in ("httpx", "requests", "urllib", "openai", "anthropic"):
        assert forbidden not in source
