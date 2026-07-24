# What is wikimem?

wikimem is a **file-first memory pipeline** for AI agents: long-term memory
stored as **plain markdown files** (one file per category, one `##` heading per
item), searched by an **in-memory BM25 index**, and connected by
**wiki-links** — `[[category:item]]` references that recall meaning-related
items keyword search cannot reach.

It is a Python library with **zero mandatory dependencies**. `pip install
wikimem` gives you the complete system: storage, retrieval (including Chinese,
via character bigrams), wiki-link expansion, and an append-only journal.

## The problem it solves

"Agent memory" usually arrives as infrastructure: a vector database for
similarity, an embedding endpoint you now depend on, sometimes a graph database
for relations, and docker-compose to hold it all together. For a personal
agent — thousands of items, not billions — that stack is upside down: the
infrastructure outweighs the data, the data is unreadable without tooling, and
every layer is a new way to lose memories.

wikimem inverts it. The memory **is** a folder of markdown files. Everything
else — the BM25 index, the optional vector cache — is derived state that can be
deleted and rebuilt from those files at any time. The design predecessor of
this project ran mem0 + Qdrant + Neo4j to do what this library does with a
text folder; the association recall the graph database was there to provide,
wiki-links deliver with a mechanical one-hop expansion.

## The four design rules

Everything in the library follows from these (fixed in XnneHangLab ADR-0001):

1. **Markdown files are the only source of truth.** One file per category
   under `category/` (`memory/category/preferences.md`), one `##` heading per
   item; diary events live as per-day files under `diary/`. Read them, edit
   them, diff them — your editor is the admin UI.
2. **No unreadable truth on disk.** Every derived artifact (indexes, vector
   caches) is deletable and rebuildable from the files. The BM25 index lives in
   memory, built at startup, never persisted.
3. **Never block the conversation.** Retrieval is synchronous, token-budgeted,
   and fail-open, with **zero LLM calls**; memorization is asynchronous and
   costs the host at most **one** LLM call per turn.
4. **What happened is always answerable.** Every mutation appends one line to
   `journal.jsonl`; retrieval can explain its scoring.

## One pipeline, no modes

There are no configuration modes to choose between. wikimem is one pipeline;
optional extras unlock enhancements that activate automatically and never
conflict:

| Install | Adds | Use case |
|---|---|---|
| `wikimem` | nothing — zero dependencies | Always fully works: storage, BM25 retrieval (Chinese via char-bigrams), wiki-links, journal |
| `wikimem[zh]` | jieba | Sharper Chinese keyword recall than bigrams — picked up automatically once installed, nothing to configure |
| `wikimem[embed]` | httpx + numpy | Semantic recall (match by meaning, not wording) — only active when you pass an `embedder`; endpoint down → BM25 carries on |
| `wikimem[all]` | both of the above | The "don't make me think" option |

Installing every extra changes nothing until you actually use it: jieba is
picked up by the tokenizer when importable, and the embedding path only runs
when you construct `MemoryIndex` with an `embedder`.

## What wikimem is not

- **Not a vector database.** There is an optional vector *cache*, but it is
  derived state — deletable, rebuildable, never the source of truth.
- **Not a graph database.** The "graph" is text: wiki-links inside item
  content. Expansion is an exact-name lookup, not a traversal engine.
- **Not a note-taking app.** The format is deliberately Obsidian-*adjacent*
  (markdown + `[[...]]`), but the unit is a few-sentence **item**, not a
  document, and the writer is usually an extraction LLM, not a person.
- **Not an agent framework.** wikimem has no opinion about your LLM, your
  prompt, or your event loop. The host wires it in — see
  [Host Integration](/guide/host-integration).

## Status

Pre-alpha (`0.1.0.dev0`), built milestone by milestone against
XnneHangLab ADR-0001:

- **M1 ✅ — storage**: category files, item model + provenance metadata,
  wiki-link parsing, `journal.jsonl`, atomic writes
- **M2 ✅ — retrieval**: in-memory BM25 (char-bigram fallback, `[zh]` extra for
  jieba), one-hop wiki-link expansion, token budget, explain
- **M3 ✅ — embedding fusion** (`[embed]` extra): content-hash vector cache
  (versioned `.npy` + plain-text keys), memmap tiers with binary quantization
  above 10k items, pluggable `VectorIndex` port, silent BM25 fallback
- **M4 — CLI** (next): `ls / show / grep / explain / graph`

## License and credits

Apache-2.0. The extraction-prompt design borrows from
[memU](https://github.com/NevaMind-AI/memU) (Apache-2.0) — adopted as design
inspiration, not as a dependency (lab ADR-0002). The BM25 + cosine fusion
formula follows what memU's ADR-0007 converged on.
