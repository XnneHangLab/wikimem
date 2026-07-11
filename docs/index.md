---
layout: home

hero:
  name: wikimem
  text: File-first memory for AI agents
  tagline: Categories + wiki-links over plain markdown. No database, no embedding model, no docker — pip install wikimem and it works.
  image:
    src: /logo.svg
    alt: wikimem
  actions:
    - theme: brand
      text: Getting Started
      link: /guide/getting-started
    - theme: alt
      text: What is wikimem?
      link: /guide/what-is-wikimem
    - theme: alt
      text: GitHub
      link: https://github.com/XnneHangLab/wikimem

features:
  - icon: 📄
    title: Markdown is the database
    details: One file per category, one ## heading per item. Read them, edit them, git-diff them — your editor is the admin UI.
  - icon: 🔗
    title: Wiki-links recall what search misses
    details: "[[category:item]] links written at memorization time connect meaning-related items that share no words. Expansion is a mechanical one-hop lookup — no LLM, no graph database."
  - icon: 🔍
    title: Zero-dependency BM25
    details: In-memory index, rebuilt free at startup. Chinese works out of the box via character bigrams; install [zh] for jieba.
  - icon: 🧭
    title: Semantic fusion, strictly optional
    details: The [embed] extra fuses BM25 with cosine similarity. BM25 is never disabled — if the endpoint is down, retrieval silently carries on.
  - icon: ⚡
    title: Never blocks the conversation
    details: "Retrieval is synchronous, token-budgeted, and makes zero LLM calls. Memorization is async and costs the host at most one."
  - icon: 🧾
    title: Always answerable
    details: Every mutation appends one line to journal.jsonl; every retrieval can explain its scoring. tail -f is your observability stack.
---

## Sixty-second taste

```python
from wikimem import MemoryIndex, MemoryStore

store = MemoryStore("memory/")
store.add("preferences", "likes-the-sea",
          "Loves the seaside, mentioned wanting a beach trip. [[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")
store.add("daily_life", "beach-trip-plan", "Planning a summer beach trip to watch the sunrise.")

index = MemoryIndex(store)  # in-memory BM25, rebuilds itself on store writes
result = index.retrieve("beach vacation", budget_tokens=800)
for entry in result.items:
    # hits come ranked; each is followed by its one-hop wiki-link targets
    print(entry.source, entry.item.name, entry.score)
```

What's on disk afterwards? Two markdown files you can open in any editor, and a
one-line-per-mutation [journal](/reference/file-format#journal-jsonl). That's the
whole system.
