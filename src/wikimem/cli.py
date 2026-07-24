"""Zero-dependency CLI (stdlib only): inspect a memory store from the shell.

``wikimem ls / show / grep / explain / graph`` over a store directory.
``graph`` parses ``[[category:item]]`` links out of the markdown and exports
the wiki-link relation graph (mermaid or json) — this takes over the
semantic-layer visualization duty from the retired Neo4j stack (lab ADR-0001,
XnneHangLab#481). No docker, no service process, no third-party imports.

Exit codes: 0 ok, 1 no match / not found, 2 usage or store errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .models import MemoryItem
from .retrieval import MemoryIndex, RetrievedItem
from .store import MemoryStore
from .tokenize import tokenize

_STORE_ENV = "WIKIMEM_STORE"


def _item_id(item: MemoryItem) -> str:
    return f"{item.category}:{item.name}"


def _render_item(item: MemoryItem) -> str:
    """Render one item the way the category file stores it."""
    parts = [f"## {item.name}", "", item.content]
    fields: list[str] = []
    if item.owner:
        fields.append(f"owner={item.owner}")
    if item.source_conv:
        fields.append(f"source={item.source_conv}")
    if item.ts:
        fields.append(f"ts={item.ts}")
    if fields:
        parts += ["", f"<!-- wikimem: {' | '.join(fields)} -->"]
    return "\n".join(parts)


# ------------------------------------------------------------------ commands


def _cmd_ls(store: MemoryStore) -> int:
    categories = store.categories()
    if not categories:
        return 0
    width = max(len(cat) for cat in categories)
    for cat in categories:
        print(f"{cat:<{width}}  {len(store.items(cat)):>4}")
    return 0


def _cmd_show(store: MemoryStore, category: str, name: str | None) -> int:
    if name is not None:
        item = store.get(category, name)
        if item is None:
            print(f"wikimem: no item {name!r} in category {category!r}", file=sys.stderr)
            return 1
        print(_render_item(item))
        return 0
    items = store.items(category)
    if not items:
        print(f"wikimem: no such category: {category}", file=sys.stderr)
        return 1
    print(f"# {category}")
    for item in items:
        print()
        print(_render_item(item))
    return 0


def _cmd_grep(store: MemoryStore, pattern: str, ignore_case: bool) -> int:
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        print(f"wikimem: bad pattern: {exc}", file=sys.stderr)
        return 2
    found = False
    for item in store.items():
        prefix = _item_id(item)
        if rx.search(item.name):
            found = True
            print(f"{prefix}:## {item.name}")
        for line in item.content.splitlines():
            if rx.search(line):
                found = True
                print(f"{prefix}:{line}")
    return 0 if found else 1


def _explain_row(pos: int, entry: RetrievedItem) -> str:
    def num(value: float | None) -> str:
        return f"{value:.3f}" if value is not None else "-"

    note = ""
    if entry.source == "hit" and entry.matched_terms:
        note = f"  [{', '.join(entry.matched_terms)}]"
    elif entry.source == "link" and entry.via:
        note = f"  (via {entry.via})"
    return (
        f"{pos:>3}  {entry.source:<4}  {num(entry.score):>7}  {num(entry.bm25_score):>7}  "
        f"{num(entry.cos_score):>5}  {entry.tokens_est:>5}  {_item_id(entry.item)}{note}"
    )


def _cmd_explain(
    store: MemoryStore,
    query: str,
    *,
    limit: int,
    budget: int | None,
    expand_links: bool,
    use_jieba: bool | None,
) -> int:
    index = MemoryIndex(store, use_jieba=use_jieba)
    result = index.retrieve(
        query, limit=limit, budget_tokens=budget, expand_links=expand_links, explain=True
    )
    print(f"query: {query}")
    print(f"query tokens: {', '.join(tokenize(query, use_jieba=use_jieba)) or '(none)'}")
    print(
        f"ranking: {'BM25 + cosine (fused)' if result.embedding_used else 'BM25 (embedding: off)'}"
    )
    if not result.items:
        print("no results")
        return 1
    print()
    print("  #  src      score     bm25    cos  ~tok  item")
    for pos, entry in enumerate(result.items, start=1):
        print(_explain_row(pos, entry))
    print()
    budget_str = str(result.budget_tokens) if result.budget_tokens is not None else "no limit"
    print(f"budget: used {result.budget_used} / {budget_str}")
    if result.dropped:
        print(f"dropped {len(result.dropped)}:")
        for entry in result.dropped:
            print(f"  {_item_id(entry.item)} ({entry.source}, ~{entry.tokens_est} tok)")
    if result.unresolved_links:
        print(f"unresolved links: {', '.join(result.unresolved_links)}")
    return 0


def _graph_data(store: MemoryStore) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Nodes and edges of the wiki-link graph, in deterministic store order.

    Link targets that do not exist in the store are still emitted as nodes
    (flagged ``unresolved``) so dangling references stay visible in the graph.
    """
    items = store.items()
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        node_id = _item_id(item)
        if node_id not in seen:
            seen.add(node_id)
            nodes.append(
                {"id": node_id, "category": item.category, "name": item.name, "unresolved": False}
            )
    for item in items:
        for link in item.links:
            target_id = f"{link.category}:{link.name}"
            if target_id not in seen:
                seen.add(target_id)
                nodes.append(
                    {
                        "id": target_id,
                        "category": link.category,
                        "name": link.name,
                        "unresolved": True,
                    }
                )
            edges.append({"source": _item_id(item), "target": target_id})
    return nodes, edges


def _cmd_graph(store: MemoryStore, fmt: str) -> int:
    nodes, edges = _graph_data(store)
    if fmt == "json":
        print(json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2))
        return 0

    # mermaid
    alias = {str(node["id"]): f"n{pos}" for pos, node in enumerate(nodes)}
    lines = ["graph LR"]
    has_unresolved = False
    for node in nodes:
        node_id = str(node["id"])
        label = node_id.replace('"', "'")
        suffix = ""
        if node["unresolved"]:
            has_unresolved = True
            suffix = ":::unresolved"
        lines.append(f'    {alias[node_id]}["{label}"]{suffix}')
    for edge in edges:
        lines.append(f"    {alias[edge['source']]} --> {alias[edge['target']]}")
    if has_unresolved:
        lines.append("    classDef unresolved stroke-dasharray: 5 5;")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- entrypoint


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikimem",
        description="Inspect a wikimem store: plain markdown in, no infra required.",
    )
    parser.add_argument(
        "-s",
        "--store",
        default=os.environ.get(_STORE_ENV, "."),
        help=f"store directory (default: ${_STORE_ENV} or current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ls", help="list categories with item counts")

    p_show = sub.add_parser("show", help="print a category (or one item) as stored")
    p_show.add_argument("category")
    p_show.add_argument("name", nargs="?", default=None)

    p_grep = sub.add_parser("grep", help="regex search over item names and content")
    p_grep.add_argument("pattern")
    p_grep.add_argument("-i", "--ignore-case", action="store_true")

    p_explain = sub.add_parser("explain", help="run retrieval and print the scoring breakdown")
    p_explain.add_argument("query")
    p_explain.add_argument("--limit", type=int, default=10, help="max ranked hits (default: 10)")
    p_explain.add_argument("--budget", type=int, default=None, help="token budget for the cut")
    p_explain.add_argument(
        "--no-links", action="store_true", help="disable one-hop wiki-link expansion"
    )
    p_explain.add_argument(
        "--jieba",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="force jieba on/off for CJK tokenization (default: auto)",
    )

    p_graph = sub.add_parser("graph", help="export the wiki-link graph")
    p_graph.add_argument("--format", choices=("mermaid", "json"), default="mermaid")

    p_serve = sub.add_parser("serve", help="serve the store over HTTP+JSON (read-only, localhost)")
    p_serve.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8787, help="bind port (default: 8787)")
    p_serve.add_argument(
        "--cors", default=None, help="Access-Control-Allow-Origin for a cross-origin frontend"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    # Store content is UTF-8 markdown (often CJK); never die on a legacy console.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="replace")

    args = _build_parser().parse_args(argv)
    store_root = Path(args.store)
    if not store_root.is_dir():
        print(f"wikimem: store directory not found: {store_root}", file=sys.stderr)
        return 2
    store = MemoryStore(store_root)

    if args.command == "ls":
        return _cmd_ls(store)
    if args.command == "show":
        return _cmd_show(store, args.category, args.name)
    if args.command == "grep":
        return _cmd_grep(store, args.pattern, args.ignore_case)
    if args.command == "explain":
        return _cmd_explain(
            store,
            args.query,
            limit=args.limit,
            budget=args.budget,
            expand_links=not args.no_links,
            use_jieba=args.jieba,
        )
    if args.command == "graph":
        return _cmd_graph(store, args.format)
    if args.command == "serve":
        from .serve import serve

        serve(store, host=args.host, port=args.port, cors=args.cors)
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
