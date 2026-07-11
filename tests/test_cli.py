import json

import pytest

from wikimem import MemoryStore
from wikimem.cli import main


@pytest.fixture()
def store_dir(tmp_path):
    root = tmp_path / "memory"
    s = MemoryStore(root)
    s.add(
        "preferences",
        "likes-the-sea",
        "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]] [[missing:gone]]",
        owner="user:xnne",
        source_conv="conv_1",
    )
    s.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")
    s.add("preferences", "coffee", "只喝手冲咖啡，不加糖。")
    return root


def run(store_dir, *argv, jieba_off=True):
    args = ["--store", str(store_dir), *argv]
    # explain is the only tokenizing command; force the dependency-free path.
    if jieba_off and argv and argv[0] == "explain":
        args += ["--no-jieba"]
    return main(args)


# ------------------------------------------------------------------------ ls


def test_ls_lists_categories_with_counts(store_dir, capsys):
    assert run(store_dir, "ls") == 0
    out = capsys.readouterr().out
    assert "daily_life" in out
    lines = {line.split()[0]: line.split()[1] for line in out.strip().splitlines()}
    assert lines["preferences"] == "2"
    assert lines["daily_life"] == "1"


def test_ls_empty_store_is_quiet(tmp_path, capsys):
    assert main(["--store", str(tmp_path), "ls"]) == 0
    assert capsys.readouterr().out == ""


def test_missing_store_dir_errors(tmp_path, capsys):
    assert main(["--store", str(tmp_path / "nope"), "ls"]) == 2
    assert "not found" in capsys.readouterr().err


def test_store_env_var_is_default(store_dir, capsys, monkeypatch):
    monkeypatch.setenv("WIKIMEM_STORE", str(store_dir))
    assert main(["ls"]) == 0
    assert "preferences" in capsys.readouterr().out


# ---------------------------------------------------------------------- show


def test_show_category_renders_items_and_meta(store_dir, capsys):
    assert run(store_dir, "show", "preferences") == 0
    out = capsys.readouterr().out
    assert "# preferences" in out
    assert "## likes-the-sea" in out
    assert "## coffee" in out
    assert "owner=user:xnne" in out
    assert "source=conv_1" in out


def test_show_single_item(store_dir, capsys):
    assert run(store_dir, "show", "preferences", "coffee") == 0
    out = capsys.readouterr().out
    assert "## coffee" in out
    assert "likes-the-sea" not in out


def test_show_missing_item_and_category(store_dir, capsys):
    assert run(store_dir, "show", "preferences", "nope") == 1
    assert "no item" in capsys.readouterr().err
    assert run(store_dir, "show", "nope") == 1
    assert "no such category" in capsys.readouterr().err


# ---------------------------------------------------------------------- grep


def test_grep_matches_content_with_item_prefix(store_dir, capsys):
    assert run(store_dir, "grep", "海边") == 0
    out = capsys.readouterr().out
    assert "preferences:likes-the-sea:" in out
    assert "daily_life:beach-trip-plan:" in out
    assert "coffee" not in out


def test_grep_matches_item_name(store_dir, capsys):
    assert run(store_dir, "grep", "coffee") == 0
    assert "preferences:coffee:## coffee" in capsys.readouterr().out


def test_grep_no_match_exits_1(store_dir):
    assert run(store_dir, "grep", "quantum") == 1


def test_grep_ignore_case(store_dir, capsys):
    assert run(store_dir, "grep", "-i", "COFFEE") == 0
    assert "coffee" in capsys.readouterr().out


def test_grep_bad_pattern_exits_2(store_dir, capsys):
    assert run(store_dir, "grep", "[") == 2
    assert "bad pattern" in capsys.readouterr().err


# ------------------------------------------------------------------- explain


def test_explain_shows_hit_link_and_unresolved(store_dir, capsys):
    assert run(store_dir, "explain", "想去海边玩") == 0
    out = capsys.readouterr().out
    assert "BM25 (embedding: off)" in out
    assert "hit" in out
    assert "preferences:likes-the-sea" in out
    # one-hop expansion row, attributed to its parent
    assert "daily_life:beach-trip-plan" in out
    assert "(via likes-the-sea)" in out
    # dangling link stays visible
    assert "[[missing:gone]]" in out
    assert "budget: used" in out


def test_explain_budget_reports_dropped(store_dir, capsys):
    assert run(store_dir, "explain", "想去海边玩", "--budget", "1") == 0
    out = capsys.readouterr().out
    assert "/ 1" in out
    assert "dropped" in out


def test_explain_no_links_skips_expansion(store_dir, capsys):
    # beach-trip-plan mentions 海边 itself, so it may still rank as a hit —
    # what --no-links must remove is link-sourced rows and their attribution.
    assert run(store_dir, "explain", "想去海边玩", "--no-links") == 0
    out = capsys.readouterr().out
    assert "preferences:likes-the-sea" in out
    assert "(via" not in out
    assert "unresolved links" not in out


def test_explain_no_results_exits_1(store_dir, capsys):
    assert run(store_dir, "explain", "quantum") == 1
    assert "no results" in capsys.readouterr().out


# --------------------------------------------------------------------- graph


def test_graph_json_nodes_edges_unresolved(store_dir, capsys):
    assert run(store_dir, "graph", "--format", "json") == 0
    data = json.loads(capsys.readouterr().out)
    nodes = {node["id"]: node for node in data["nodes"]}
    assert nodes["preferences:likes-the-sea"]["unresolved"] is False
    assert nodes["missing:gone"]["unresolved"] is True
    assert {"source": "preferences:likes-the-sea", "target": "daily_life:beach-trip-plan"} in data[
        "edges"
    ]


def test_graph_mermaid_renders_edges(store_dir, capsys):
    assert run(store_dir, "graph") == 0
    out = capsys.readouterr().out
    assert out.startswith("graph LR")
    assert '["preferences:likes-the-sea"]' in out
    assert "-->" in out
    # dangling target gets the dashed style
    assert ":::unresolved" in out
    assert "classDef unresolved" in out
