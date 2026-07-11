# Getting Started

## Install

```bash
pip install wikimem        # the default — everything works out of the box
pip install "wikimem[all]" # optional enhancements included, if you'd rather not choose
```

Requires Python ≥ 3.11. The base install has **zero dependencies**; see
[the extras table](/guide/what-is-wikimem#one-pipeline-no-modes) for what
`[zh]` and `[embed]` add.

## Write your first memories

```python
from wikimem import MemoryStore

store = MemoryStore("memory/")

store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")
store.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")
```

`add` inserts a new item or replaces the same-named one — that's the whole
update model. Now look at what it wrote:

```markdown
<!-- memory/preferences.md -->
# preferences

## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->
```

A category is a markdown file; an item is a `##` section; provenance lives in
an HTML comment; the `[[daily_life:beach-trip-plan]]` wiki-link is plain text
in the content. Nothing here needs wikimem to be read.

::: tip Naming rules
Category names are lowercase ASCII slugs (`daily_life`, `preferences`) — they
double as filenames and link prefixes. Item names may be any language but must
avoid `[[ ]] : | #`. See [On-disk Format](/reference/file-format) for the
exact rules.
:::

## Retrieve

```python
from wikimem import MemoryIndex

index = MemoryIndex(store)  # in-memory BM25, rebuilds itself on store writes
result = index.retrieve("想去海边玩", budget_tokens=800)

for entry in result.items:
    print(entry.source, entry.item.name, entry.score, entry.matched_terms)
# hit  likes-the-sea    3.87  ['海边', '想去', ...]
# link beach-trip-plan  None  []
```

Three things happened, all without an LLM call:

1. **BM25 ranked** every item against the query (Chinese tokenized as
   character bigrams by default, jieba if installed).
2. Each hit's wiki-links were **expanded one hop**: `likes-the-sea` links to
   `beach-trip-plan`, so the full target item rides along, marked
   `source="link"`.
3. The sequence was **trimmed to your token budget** (`budget_tokens=800`),
   keeping injection order: each hit followed by its link targets.

`result` also tells you `budget_used`, which links didn't resolve
(`unresolved_links`), and — with `explain=True` — exactly what was dropped and
why. Details in [Retrieval](/guide/retrieval).

## What's on disk

```
memory/
├── preferences.md    ← source of truth
├── daily_life.md     ← source of truth
└── journal.jsonl     ← append-only audit log, one line per mutation
```

That's everything the base pipeline persists. The BM25 index lives in memory
and is rebuilt from the files at startup — there is nothing to migrate, back
up, or corrupt. If you enable [embedding fusion](/guide/embedding-fusion), a
vector cache (`vectors-*.npy` + `vectors.keys.jsonl`) appears next to the
markdown; it is a cache, and deleting it is always safe.

## Edit by hand

The files are yours. Fix a typo, delete an embarrassing item, add a wiki-link
in your editor — reads are deliberately tolerant, so hand edits never crash
the pipeline. Two things to know:

- The store bumps an internal revision on its **own** writes, and the index
  rebuilds lazily from that. Edits made **outside** the process (your editor,
  git checkout) are picked up by calling `index.rebuild()` — or just
  restarting, since the index is rebuilt at startup anyway.
- If you duplicate an item heading by hand, the **last occurrence wins** on
  read; the duplicate disappears on the next write of that category.

## Next steps

- [Wiki-links](/guide/wiki-links) — the idea that replaces the graph database
- [Retrieval](/guide/retrieval) — scoring, budget, and explain, in detail
- [Embedding Fusion](/guide/embedding-fusion) — optional semantic recall
- [Host Integration](/guide/host-integration) — wiring wikimem into an agent
