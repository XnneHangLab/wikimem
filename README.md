# wikimem

English | [简体中文](README.zh-CN.md)

<!-- Keep in sync with README.zh-CN.md: update both when either changes -->

File-first memory for AI agents: **categories + wiki-links over plain markdown**.
No database, no embedding model, no docker — `pip install wikimem` and it works.

## Design rules

1. **Markdown files are the only source of truth.** One file per category
   (`memory/preferences.md`), one `##` heading per item. Read them, edit them,
   diff them — your editor is the admin UI.
2. **No unreadable truth on disk.** Every derived artifact (indexes, vector
   caches) is deletable and rebuildable from the files. The BM25 index lives in
   memory, built at startup.
3. **Never block the conversation.** Retrieval is synchronous, budgeted, and
   fail-open (0 LLM calls); memorization is async (≤ 1 LLM call by the host).
4. **What happened is always answerable.** Every mutation appends one line to
   `journal.jsonl`; retrieval can explain its scoring.

## Wiki-links: what and why

A wiki-link is an in-content reference — the `[[...]]` syntax you may know
from wikis and Obsidian — and in wikimem it always points at **one item**:

```markdown
# preferences.md
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->

# daily_life.md
## beach-trip-plan

计划夏天去海边旅行，看日出。
```

`[[daily_life:beach-trip-plan]]` is an address with two parts:
**category** (which file — `daily_life.md`) and **item name** (which `##`
heading inside it). So the linked node is an *item*: a named, self-contained
entry of a few sentences — **not a word, and not a whole file**. When
retrieval hits `likes-the-sea`, it mechanically expands its links one hop and
injects the whole `beach-trip-plan` item alongside — no LLM call, no graph
database; the "graph" is just text, and expansion is an exact-name lookup.

Why links, when there's already search?

- **Search finds similar wording; links encode related meaning.** A coffee
  preference and a morning routine may share no words — no keyword (often not
  even embedding) match connects them. A link written at memorization time
  does.
- **One unit everywhere.** The link target is the same unit retrieval ranks
  and the token budget trims: an item. Finer-grained than Obsidian's
  file-sized notes, so expanding a link never dumps an entire document into
  the prompt.
- **Readable and writable by everyone.** The extraction LLM emits links in
  the same single pass that writes the memory; you can add or fix them in any
  text editor; `git diff` shows them.
- **Zero infrastructure, fail-soft.** This replaces a graph database (the
  design it supersedes ran Neo4j for exactly this). A dangling link — target
  renamed or deleted — is tolerated and reported, never a crash.

## Status

Pre-alpha, built milestone by milestone
(design: XnneHangLab ADR-0001 — memory pipeline):

- M1 ✅ — storage layer: category files, item model + metadata,
  wiki-link parsing, `journal.jsonl`, atomic writes
- M2 ✅ — retrieval: in-memory BM25 (char-bigram fallback, `[zh]` extra
  for jieba), one-hop wiki-link expansion, token budget, explain
- **M3 (this)** — optional embedding fusion (`[embed]` extra): content-hash
  vector cache (versioned `.npy` + plain-text keys), memmap tiers with binary
  quantization above 10k items, pluggable `VectorIndex` port, silent BM25
  fallback when the endpoint is down
- M4 — CLI: `ls / show / grep / explain / graph`

## Quick start

```python
from wikimem import MemoryIndex, MemoryStore

store = MemoryStore("memory/")
store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")
store.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")

index = MemoryIndex(store)  # in-memory BM25, rebuilds itself on store writes
result = index.retrieve("想去海边玩", budget_tokens=800)
for entry in result.items:
    # hits come ranked; each is followed by its one-hop wiki-link targets
    print(entry.source, entry.item.name, entry.score, entry.matched_terms)
```

Retrieval makes zero LLM calls and never persists the BM25 index — delete
nothing, lose nothing. Install `wikimem[zh]` for jieba-based Chinese
tokenization (default is character bigrams).

Optional semantic fusion (`pip install wikimem[embed]`) — BM25 catches the
wording, cosine catches the meaning, min-max fused:

```python
from wikimem.vectors import HttpEmbedder

embedder = HttpEmbedder("https://api.example.com/v1", "bge-m3", api_key="sk-…")
index = MemoryIndex(store, embedder=embedder)
result = index.retrieve("海滨度假")   # finds 喜欢海边 even with zero shared words
print(result.embedding_used)          # False = endpoint was down, BM25 carried on
```

Vectors live in a content-hash cache next to your markdown (versioned
`vectors-*.npy` + readable `vectors.keys.jsonl`) — incrementally updated,
deletable anytime, never the source of truth. An unreachable embedding
endpoint silently degrades retrieval to BM25-only; it never raises.

## Development

```bash
uv sync
uv run pytest
```

Apache-2.0. Extraction-prompt design borrows from
[memU](https://github.com/NevaMind-AI/memU) (Apache-2.0) — see lab ADR-0002.
