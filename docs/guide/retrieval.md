# Retrieval

```python
result = index.retrieve(
    "想去海边玩",
    limit=10,           # max search hits (before link expansion)
    budget_tokens=800,  # cap on injected content, None = uncapped
    expand_links=True,  # one-hop wiki-link expansion
    explain=False,      # True → keep what the budget dropped, for inspection
)
```

`retrieve` is **synchronous**, makes **zero LLM calls**, and never raises for
degraded optional paths — it is designed to sit directly on an agent's hot
path, wrapped fail-open by the host. This page walks through the pipeline in
execution order.

## 1. Tokenization

Queries and documents go through the same zero-dependency tokenizer:

- ASCII/latin runs → lowercased words (`[a-z0-9]+`).
- CJK runs → **character bigrams** ("海边玩" → `海边`, `边玩`) — good keyword
  recall with no segmenter installed.
- With the `[zh]` extra installed, CJK runs go through **jieba** instead.
  Detection is automatic; `MemoryIndex(store, use_jieba=...)` forces the path
  (`True` still falls back to bigrams when jieba is absent, `False` never uses
  it — useful for reproducible benchmarks).

## 2. BM25 ranking

Every item is scored against the query with classic BM25
(`k1 = 1.5`, `b = 0.75`), over an index of the item's **name + content**. The
index is:

- **In-memory only** — never persisted; rebuilding from a few MB of markdown
  is effectively free at personal-memory scale.
- **Lazily fresh** — every `MemoryStore` write bumps a revision counter, and
  `retrieve` rebuilds the index if it is stale. Out-of-band file edits (your
  editor, `git pull`) are invisible to the counter — call `index.rebuild()`
  after those, or rely on the rebuild at process start.

The top `limit` items by score become **hits**. If an
[embedder is configured](/guide/embedding-fusion), cosine scores are fused
with BM25 at this stage — BM25 itself is never disabled.

## 3. One-hop link expansion

With `expand_links=True` (the default), each hit's wiki-links are resolved by
exact `(category, name)` lookup and the target items are appended **directly
after their hit**, marked `source="link"`:

```text
hit   likes-the-sea      score=3.87   matched_terms=['海边', ...]
link  beach-trip-plan    via='likes-the-sea'
hit   三亚之行            score=2.41   ...
```

- Expansion is **one hop** and mechanical — no scoring, no LLM, no recursion
  (see [why](/guide/wiki-links#scope-one-hop-by-design)).
- Duplicates are removed across the whole sequence: an item already present
  (as a hit or an earlier link target) is not injected twice.
- Links whose target doesn't exist are skipped and reported in
  `result.unresolved_links`.

## 4. Token budget

The sequence is trimmed to `budget_tokens` with a **prefix cut**: entries are
kept in injection order until the next one would exceed the budget. Two
properties matter:

- **The first entry always survives**, even if it alone exceeds the budget —
  retrieval never returns nothing because the best hit was long.
- Costs use `est_tokens`, a deliberately crude estimate (one token per latin
  word, one per CJK character). It exists for **stable trimming**, not
  accuracy — don't reuse it for API billing math.

`result.budget_used` reports the estimated total of what survived.

## 5. Reading the result

```python
result = index.retrieve("咖啡", budget_tokens=800, explain=True)

result.items             # list[RetrievedItem] — survived the budget, injection order
result.budget_used       # estimated tokens of the above
result.embedding_used    # True only when the cosine path actually ran
result.unresolved_links  # ['[[daily_life:renamed-item]]', ...]
result.dropped           # what the budget cut (explain=True only)
```

Each `RetrievedItem` carries its evidence:

| field | meaning |
|---|---|
| `source` | `"hit"` (search match) or `"link"` (one-hop expansion) |
| `score` | ranking score — fused when embedding ran, else BM25 |
| `bm25_score` / `cos_score` | the raw signals behind `score` (hits only) |
| `via` | for links: the hit item that pulled this in |
| `matched_terms` | query terms found in this item — the "why" of a hit |
| `tokens_est` | what this entry cost the budget |

This is design rule 4 in practice: a host can log, display, or debug exactly
why each memory reached the prompt.

## Edge cases worth knowing

- **Empty query terms** (e.g. punctuation-only query) → empty result, unless
  the embedding path is active — cosine can still rank what BM25 cannot.
- **`add` of an existing name is an update** — the index picks it up via the
  revision counter on the next `retrieve`.
- **Scores are corpus-relative.** BM25 depends on document frequencies, and
  fused scores are min-max normalized per query — compare within one result,
  not across queries or stores.
