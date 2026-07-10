import json

from wikimem import MemoryStore


def test_every_mutation_appends_one_json_line(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    store.add("preferences", "likes-the-sea", "v1", owner="user:xnne")
    store.add("preferences", "likes-the-sea", "v2", owner="user:xnne")
    store.remove("preferences", "likes-the-sea")

    raw = (tmp_path / "memory" / "journal.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in raw.strip().splitlines()]
    assert [entry["action"] for entry in lines] == ["add", "update", "remove"]
    assert all(entry["ts"] for entry in lines)
    assert lines[0]["owner"] == "user:xnne"
    assert lines[0]["category"] == "preferences"
    assert lines[0]["item"] == "likes-the-sea"


def test_entries_reads_back(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    store.add("notes", "中文条目", "内容")
    entries = store.journal.entries()
    assert len(entries) == 1
    assert entries[0]["item"] == "中文条目"


def test_journal_is_not_a_category(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    store.add("notes", "n", "x")
    assert store.categories() == ["notes"]
