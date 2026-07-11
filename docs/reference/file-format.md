# On-disk Format

Everything wikimem persists is designed to be read (and mostly written) by
humans. A complete memory directory:

```
memory/
├── preferences.md        ← source of truth (one file per category)
├── daily_life.md         ← source of truth
├── journal.jsonl         ← append-only audit log
├── vectors-000003.npy    ← derived: vector cache ([embed] only)
└── vectors.keys.jsonl    ← derived: cache key map ([embed] only)
```

**Deletability rule of thumb:** the `.md` files are the memory; everything
else can be deleted at any time and rebuilds automatically (the journal is
history — deleting it loses the audit trail but no memories; the BM25 index
never even touches disk).

## Category files

One markdown file per category, one `##` section per item:

```markdown
# preferences

## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->

## 手冲咖啡

只喝手冲咖啡，从不加糖。
```

Serialized parts, in order per item: the `## name` heading, a blank line, the
content (stored stripped), a blank line, and — only when any provenance field
is set — the metadata comment.

### Naming

- **Category** = filename stem = link prefix. Must match
  `[a-z0-9_][a-z0-9_-]*` (lowercase ASCII slug). Enforced on write.
- **Item name** = heading text = link target. Any language; whitespace runs
  collapse to one space; must not contain `[[`, `]]`, `:`, `|`, `#`.
  Enforced on write.

### The metadata comment

```
<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->
```

- Fields are `key=value` pairs separated by `|`; recognized keys: `owner`,
  `source` (surfaced as `MemoryItem.source_conv`), `ts` (ISO-8601 UTC).
- All fields are optional; the whole comment is omitted when empty.
- Because `|` is the separator, a literal `|` inside an owner/source value is
  replaced with `/` at write time.

### Read tolerance (hand edits welcome)

Reading is deliberately liberal — these are guarantees, not accidents:

| you did this | wikimem does this |
|---|---|
| wrote an item by hand, no metadata comment | fine — `owner`/`source_conv`/`ts` are `None` |
| duplicated a `##` heading | last occurrence wins; collapses on next write |
| left prose above the first `##` | ignored (file title/preamble belongs to no item) |
| malformed metadata comment | treated as content, not an error |
| renamed/deleted a link target | link dangles: skipped at expansion, reported in `unresolved_links` |

Writing is the strict side: every mutation validates names, rewrites the
whole category file via temp file + atomic `os.replace`, and appends a
journal line. Removing a category's last item deletes the file.

::: warning Out-of-band edits
Hand edits don't bump the store's revision counter — a running
`MemoryIndex` won't see them until you call `rebuild()` (or restart the
process; the index is in-memory and rebuilt at startup anyway).
:::

## Wiki-link syntax

`[[category:name]]` inside item content. Category is everything up to the
**first** colon; neither side may contain `[`, `]`, `:` or a newline;
surrounding whitespace is trimmed; malformed links are ignored by the parser.
Rationale and behavior: [Wiki-links](/guide/wiki-links).

## journal.jsonl

One JSON object per line, appended on every mutation —
`tail -f journal.jsonl` is the live answer to "what happened to my memory":

```json
{"ts": "2026-07-10T03:00:00+00:00", "action": "add", "category": "preferences", "item": "likes-the-sea", "owner": "user:xnne", "source_conv": "conv_20260710"}
{"ts": "2026-07-10T03:05:12+00:00", "action": "update", "category": "preferences", "item": "likes-the-sea", "owner": "user:xnne"}
{"ts": "2026-07-10T04:11:40+00:00", "action": "remove", "category": "daily_life", "item": "beach-trip-plan"}
```

| field | present | meaning |
|---|---|---|
| `ts` | always | ISO-8601 UTC, second precision |
| `action` | always | `add` \| `update` (same-name replace) \| `remove` |
| `category`, `item` | always | what was touched |
| `owner`, `source_conv`, `detail` | when provided | provenance / free-form note |

Non-ASCII is stored raw (`ensure_ascii=False`) — the journal is meant to be
read in a pager, not decoded.

## Vector cache (`[embed]` extra)

Derived state with one nuance: vectors cost embedding-API money to recompute,
so unlike the BM25 index they are cached persistently — but they are still
**never the source of truth**, and deleting both files is always safe.

### `vectors.keys.jsonl`

Plain text, so *what maps to what* stays readable:

```json
{"vectors_file": "vectors-000003.npy"}
{"category": "preferences", "name": "likes-the-sea", "hash": "9f8a…"}
{"category": "daily_life", "name": "beach-trip-plan", "hash": "b774…"}
```

Header line names the current matrix file; then one line per row, in matrix
row order. `hash` is the sha256 of the embedded text (`name\ncontent`) —
the key that makes syncs incremental (unchanged hash = no API call).

### `vectors-NNNNNN.npy`

Float32 matrix, one row per key line, loaded memory-mapped. The counter
suffix exists because **Windows forbids replacing a file that a live index
still memory-maps** — each sync writes a new version and removes old ones
best-effort (leftovers are swept by later syncs).

Torn state — keys file without matrix, or row-count mismatch — is treated as
"no cache" and rebuilt on the next sync. Corruption is never trusted.
