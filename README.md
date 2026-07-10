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

Cross-category association uses in-content wiki-links:

```markdown
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->
```

Retrieval hits an item, then mechanically expands its links one hop — no LLM,
no graph database.

## Status

Pre-alpha, built milestone by milestone
(design: XnneHangLab ADR-0001 — memory pipeline):

- **M1 (this)** — storage layer: category files, item model + metadata,
  wiki-link parsing, `journal.jsonl`, atomic writes
- M2 — retrieval: in-memory BM25 (char n-gram fallback, `[zh]` extra for jieba),
  wiki-link expansion, token budget, `explain`
- M3 — optional embedding fusion (`[embed]` extra): memmap vectors, binary
  quantization ≥10k items, pluggable `VectorIndex` port
- M4 — CLI: `ls / show / grep / explain / graph`

## Quick start (M1 surface)

```python
from wikimem import MemoryStore

store = MemoryStore("memory/")
store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")

item = store.get("preferences", "likes-the-sea")
print(item.links)          # [WikiLink(category='daily_life', name='beach-trip-plan')]
print(store.categories())  # ['preferences']
```

## Development

```bash
uv sync
uv run pytest
```

Apache-2.0. Extraction-prompt design borrows from
[memU](https://github.com/NevaMind-AI/memU) (Apache-2.0) — see lab ADR-0002.
