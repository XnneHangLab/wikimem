# CLI

The package ships a zero-dependency command line tool (stdlib only — no
docker, no service process) for inspecting a store from the shell:

```bash
wikimem --store ./memory <command>    # or: python -m wikimem
```

`--store` / `-s` defaults to the `WIKIMEM_STORE` environment variable, then
the current directory.

Exit codes follow shell conventions: `0` ok, `1` no match / not found,
`2` usage or store errors.

## `ls`

Categories with item counts:

```
$ wikimem -s ./memory ls
daily_life      1
preferences     2
```

## `show <category> [name]`

Prints a category — or a single item — exactly the way the file stores it
(headings, content, provenance comment):

```
$ wikimem -s ./memory show preferences likes-the-sea
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | ts=2026-07-10T03:00:00+00:00 -->
```

## `grep <pattern> [-i]`

Regex search over item names and content, grep-style output prefixed with
`category:name`:

```
$ wikimem -s ./memory grep 海边
preferences:likes-the-sea:喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]
daily_life:beach-trip-plan:计划夏天去海边旅行，看日出。
```

## `explain "<query>"`

Runs real retrieval (`MemoryIndex.retrieve(..., explain=True)`) and prints
the scoring breakdown: ranked hits, one-hop link expansions with their
parent, token estimates, the budget cut, and dangling links.

```
$ wikimem -s ./memory explain "想去海边玩"
query: 想去海边玩
query tokens: 想去, 去海, 海边, 边玩
ranking: BM25 (embedding: off)

  #  src      score     bm25    cos  ~tok  item
  1  hit     1.676    1.676      -     22  preferences:likes-the-sea  [去海, 海边, ...]
  2  link        -        -      -     15  daily_life:beach-trip-plan  (via likes-the-sea)

budget: used 37 / no limit
unresolved links: [[missing:gone]]
```

Flags: `--limit N` (ranked hits, default 10), `--budget N` (token budget —
dropped entries are listed), `--no-links` (disable one-hop expansion),
`--jieba` / `--no-jieba` (force the CJK tokenizer path; default auto).

The CLI always runs the BM25 path — embedding fusion needs an endpoint and
belongs to host configuration, not shell inspection.

## `graph [--format mermaid|json]`

Parses `[[category:item]]` links out of the markdown and exports the
wiki-link relation graph. This is the replacement for the retired Neo4j
semantic-layer visualization: no infrastructure, same picture.

```
$ wikimem -s ./memory graph
graph LR
    n0["daily_life:beach-trip-plan"]
    n1["preferences:likes-the-sea"]
    n2["missing:gone"]:::unresolved
    n1 --> n0
    n1 --> n2
    classDef unresolved stroke-dasharray: 5 5;
```

Paste mermaid output straight into any markdown renderer. Link targets that
don't exist in the store are kept as dashed `unresolved` nodes so dangling
references stay visible.

`--format json` emits `{"nodes": [...], "edges": [...]}` (each node:
`id` / `category` / `name` / `unresolved`) for host frontends to render
themselves.
