import pytest

from wikimem import MemoryStore, sanitize_item_name, validate_category


@pytest.fixture()
def store(tmp_path):
    return MemoryStore(tmp_path / "memory")


def test_add_and_get_roundtrip(store):
    store.add(
        "preferences",
        "likes-the-sea",
        "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
        owner="user:xnne",
        source_conv="conv_20260710",
    )
    item = store.get("preferences", "likes-the-sea")
    assert item is not None
    assert item.owner == "user:xnne"
    assert item.source_conv == "conv_20260710"
    assert item.ts  # stamped automatically
    assert [link.category for link in item.links] == ["daily_life"]


def test_file_is_human_readable_markdown(store, tmp_path):
    store.add("preferences", "likes-the-sea", "喜欢海。", owner="user:xnne")
    text = (tmp_path / "memory" / "preferences.md").read_text(encoding="utf-8")
    assert text.startswith("# preferences\n")
    assert "## likes-the-sea" in text
    assert "<!-- wikimem: owner=user:xnne" in text


def test_add_same_name_updates_in_place(store):
    store.add("preferences", "likes-the-sea", "v1")
    store.add("preferences", "likes-the-sea", "v2")
    items = store.items("preferences")
    assert len(items) == 1
    assert items[0].content == "v2"


def test_remove(store):
    store.add("preferences", "likes-the-sea", "x")
    assert store.remove("preferences", "likes-the-sea") is True
    assert store.get("preferences", "likes-the-sea") is None
    assert store.remove("preferences", "likes-the-sea") is False


def test_removing_last_item_removes_file(store, tmp_path):
    store.add("preferences", "only-one", "x")
    store.remove("preferences", "only-one")
    assert not (tmp_path / "memory" / "preferences.md").exists()
    assert store.categories() == []


def test_hand_edited_item_without_metadata_is_tolerated(store, tmp_path):
    root = tmp_path / "memory"
    root.mkdir(parents=True)
    (root / "notes.md").write_text(
        "# notes\n\n## 手写条目\n\n用户直接在文件里写的，没有元数据注释。\n",
        encoding="utf-8",
    )
    item = store.get("notes", "手写条目")
    assert item is not None
    assert item.owner is None and item.ts is None
    assert "直接在文件里写的" in item.content


def test_duplicate_headings_last_wins(store, tmp_path):
    root = tmp_path / "memory"
    root.mkdir(parents=True)
    (root / "notes.md").write_text(
        "# notes\n\n## same\n\nold\n\n## same\n\nnew\n",
        encoding="utf-8",
    )
    items = store.items("notes")
    assert len(items) == 1
    assert items[0].content == "new"


def test_roundtrip_preserves_hand_written_items(store):
    store.add("notes", "第一条", "内容一")
    store.add("notes", "第二条", "内容二")
    store.add("notes", "第一条", "内容一改")  # rewrite file
    names = sorted(item.name for item in store.items("notes"))
    assert names == ["第一条", "第二条"]


def test_categories_listing(store):
    store.add("preferences", "a", "x")
    store.add("daily_life", "b", "y")
    assert store.categories() == ["daily_life", "preferences"]


def test_category_validation():
    for bad in ("Preferences", "日常", "has space", "-lead", ""):
        with pytest.raises(ValueError):
            validate_category(bad)
    assert validate_category("daily_life-2") == "daily_life-2"


def test_item_name_sanitization():
    assert sanitize_item_name("  likes   the sea ") == "likes the sea"
    for bad in ("", "a:b", "a|b", "a#b", "x[[y", "x]]y"):
        with pytest.raises(ValueError):
            sanitize_item_name(bad)


def test_metadata_pipe_is_escaped(store):
    store.add("notes", "n", "x", owner="a|b")
    item = store.get("notes", "n")
    assert item.owner == "a/b"
