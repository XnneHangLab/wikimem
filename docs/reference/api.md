# Core API

Everything below is importable from the top-level package and works with the
zero-dependency install:

```python
from wikimem import (
    MemoryStore, MemoryIndex, Journal, Diary,
    MemoryItem, DiaryEntry, WikiLink, RetrievalResult, RetrievedItem,
    tokenize, est_tokens, parse_wiki_links,
    validate_category, sanitize_item_name,
)
```

The optional embedding layer lives in `wikimem.vectors` and is documented
[separately](/reference/vectors) — it is deliberately **not** re-exported
here, so importing `wikimem` never touches numpy.

## MemoryStore

```python
MemoryStore(root: Path | str)
```

Read/write access to a store's wiki categories, which live as markdown files
under `root / "category/"`. Creating the store does not touch the filesystem;
directories appear on first write. The store owns a [`Journal`](#journal) at
`root / "journal.jsonl"`, and exposes the event-stream primitive at
[`store.diary`](#diary) (which shares that journal).

### Reads

Reads are **tolerant by design** — hand-edited files must never crash a read
(exact parsing rules in [On-disk Format](/reference/file-format)).

| method | returns |
|---|---|
| `categories()` | sorted category names — one per `*.md` file in `root / "category/"` |
| `items(category=None)` | all items, or one category's |
| `get(category, name)` | the item, or `None` (name is whitespace-normalized before comparing) |

### Writes

Writes are **strict** (validated names) and **atomic** (temp file +
`os.replace` per category file), and each appends one journal line.

```python
store.add(
    "preferences",            # category: lowercase slug (validated)
    "likes-the-sea",          # item name (sanitized)
    "喜欢海边。[[daily_life:beach-trip-plan]]",
    owner="user:xnne",        # optional provenance
    source_conv="conv_001",   # optional provenance
    ts=None,                  # optional ISO-8601; defaults to now (UTC)
) -> MemoryItem
```

- `add` **inserts or replaces**: an existing item with the same name is
  overwritten, and the journal records `update` instead of `add`. This is the
  update model — there is no separate `update()`.
- `remove(category, name, *, owner=None) -> bool` — `False` if the name
  wasn't present. Removing a category's last item deletes its file.
- Raises `ValueError` for an invalid category slug or reserved characters in
  the item name (see below). Content is stored `strip()`ed.

### `revision`

An integer bumped on every successful **in-process** write; `MemoryIndex`
uses it to rebuild lazily. Out-of-band file edits do not bump it — call
`index.rebuild()` after those. Diary writes do **not** bump it — the wiki BM25
index is not built over diary files.

## Diary

```python
store.diary            # -> Diary, lazily constructed, shares the store's journal
Diary(root, *, journal=None)   # or construct standalone
```

The **event-stream** primitive (ADR-0001): where the wiki is state ("what is
true now"), the diary is events ("what happened, and when"). Entries live as
`## HH:MM` sections in per-day files `root / "diary" / "YYYY-MM-DD.md"`, in the
same serialization as wiki items (exact rules in
[On-disk Format](/reference/file-format#diary-files-diary)).

### Writes

```python
store.diary.append(
    "他说换了工作，语气很兴奋。[[work:current-job]]",
    ts=None,          # optional ISO-8601 instant; defaults to now (UTC)
    date=None,        # optional YYYY-MM-DD; defaults to ts rendered in tz
    time=None,        # optional HH:MM;     defaults to ts rendered in tz
    owner=None,       # optional provenance
    source_conv=None, # optional provenance
    tz=None,          # zone for the default date/time (default: system local)
) -> DiaryEntry
```

**Append-only** — this is the only write. There is deliberately no edit or
delete: entries are only ever added, and the journal records one `diary` line
per append. Two events may share a minute; both are kept (unlike the wiki's
last-wins). Raises `ValueError` on empty content or a malformed `date` / `time`.

### Reads

| method | returns |
|---|---|
| `day(date)` | entries for one `YYYY-MM-DD`, in chronological (file) order |
| `dates()` | every day that has a file, ascending |

`ts` is stored UTC; `date` / `time` are the human-local day and wall clock. The
inclusive multi-day `window(start, end)` range read is planned (Phase 3, the
ground [ADR-0002](/reference/file-format)'s time gate builds on).

## Naming helpers

```python
validate_category(category: str) -> str    # raises ValueError if invalid
sanitize_item_name(name: str) -> str       # raises ValueError if invalid
```

- **Categories** must match `[a-z0-9_][a-z0-9_-]*` — lowercase ASCII slugs,
  because they double as filenames and link prefixes.
- **Item names** may be any language; whitespace runs collapse to single
  spaces; the characters `[[`, `]]`, `:`, `|`, `#` are rejected (they would
  break headings, links, or metadata).

## MemoryItem / DiaryEntry / WikiLink

```python
@dataclass
class MemoryItem:                   # wiki: the retrieval unit (state)
    category: str
    name: str
    content: str
    owner: str | None = None        # None for hand-written items — tolerated
    source_conv: str | None = None
    ts: str | None = None           # ISO-8601 UTC string

    @property
    def links(self) -> list[WikiLink]   # parsed from content on access
```

```python
@dataclass
class DiaryEntry:                   # diary: one event (parallel to MemoryItem)
    date: str                       # YYYY-MM-DD — the day file
    time: str                       # HH:MM — the heading (human-local wall clock)
    content: str
    owner: str | None = None
    source_conv: str | None = None
    ts: str | None = None           # ISO-8601 UTC instant

    @property
    def links(self) -> list[WikiLink]   # same wiki-link parsing as MemoryItem
```

```python
@dataclass(frozen=True)
class WikiLink:
    category: str
    name: str
    def render(self) -> str    # "[[category:name]]"
```

`parse_wiki_links(text: str) -> list[WikiLink]` extracts links in order of
appearance; malformed links are ignored, not errors.

## MemoryIndex

```python
MemoryIndex(
    store: MemoryStore,
    *,
    use_jieba: bool | None = None,     # None = auto-detect the [zh] extra
    embedder = None,                   # activates fusion — see Vectors API
    vectors_dir: Path | str | None = None,  # vector cache location, default: store root
    fusion_weight: float = 0.5,        # BM25 share of the fused score
    binary_threshold: int = 10_000,    # memmap tier switch — see Vectors API
)
```

BM25 (+ optional embedding fusion) over a `MemoryStore`. The BM25 index is
in-memory derived state: built on first use, rebuilt automatically when
`store.revision` changes, never persisted.

- `rebuild()` — rescan the store now. Needed only after out-of-band file
  edits; cheap at personal-memory scale.
- `retrieve(query, *, limit=10, budget_tokens=None, expand_links=True,
  explain=False) -> RetrievalResult` — rank, expand one hop, trim to budget.
  Zero LLM calls, synchronous, never raises for a degraded embedding path.
  Semantics: [Retrieval](/guide/retrieval).

## RetrievalResult

| field | type | meaning |
|---|---|---|
| `items` | `list[RetrievedItem]` | survived the budget, in injection order |
| `budget_tokens` | `int \| None` | the cap that was applied (`None` = uncapped) |
| `budget_used` | `int` | estimated tokens of `items` |
| `embedding_used` | `bool` | `True` only when the cosine path actually ran |
| `dropped` | `list[RetrievedItem]` | what the budget cut — populated only with `explain=True` |
| `unresolved_links` | `list[str]` | rendered links whose target is missing, e.g. `"[[a:b]]"` |

## RetrievedItem

| field | type | meaning |
|---|---|---|
| `item` | `MemoryItem` | the memory itself |
| `source` | `str` | `"hit"` (search match) or `"link"` (one-hop expansion) |
| `score` | `float \| None` | ranking score: fused when embedding ran, else BM25; `None` for links |
| `bm25_score` | `float \| None` | raw BM25 component (hits only) |
| `cos_score` | `float \| None` | raw cosine component (hits, fusion runs only) |
| `via` | `str \| None` | for links: name of the hit that pulled this in |
| `matched_terms` | `list[str]` | query terms present in this item (sorted) |
| `tokens_est` | `int` | budget cost of this entry |

## Journal

```python
Journal(path: Path | str)

journal.append(action, *, category, name,
               owner=None, source_conv=None, detail=None)   # wiki mutations
journal.append_diary(*, date, time, owner=None, source_conv=None)  # diary appends
journal.entries() -> list[dict]
```

Append-only JSONL log, shared by both primitives. `MemoryStore` writes it
automatically (`add` / `update` / `remove`), and `Diary.append` writes the
`diary` line — you rarely construct one yourself. Line schema:
[On-disk Format](/reference/file-format#journal-jsonl).

## Tokenization

```python
tokenize(text: str, *, use_jieba: bool | None = None) -> list[str]
```

Lowercased latin words (`[a-z0-9]+`) plus CJK handling: character bigrams by
default, jieba when the `[zh]` extra is importable. `use_jieba=None`
auto-detects; `True` forces jieba (still falls back to bigrams if absent);
`False` forces bigrams — useful for reproducible benchmarks.

```python
est_tokens(text: str) -> int
```

Rough LLM-token estimate: one per latin word, one per CJK character. Used for
budget trimming, where **stability matters more than accuracy** — not
suitable for billing math.
