# Wiki-links

A wiki-link is an in-content reference — the `[[...]]` syntax you may know
from wikis and Obsidian — and in wikimem it always points at **one item**:

```markdown
# preferences.md
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

# daily_life.md
## beach-trip-plan

计划夏天去海边旅行，看日出。
```

`[[daily_life:beach-trip-plan]]` is an address with two parts: **category**
(which file — `daily_life.md`) and **item name** (which `##` heading inside
it). So the linked node is an *item*: a named, self-contained entry of a few
sentences — **not a word, and not a whole file**.

When retrieval hits `likes-the-sea`, it mechanically expands its links one hop
and injects the whole `beach-trip-plan` item alongside — no LLM call, no graph
database. The "graph" is just text, and expansion is an exact-name lookup.

## Why links, when there's already search?

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

## Who writes the links?

Anyone who can type two brackets:

- **The extraction LLM**, in the same pass that writes the memory. The host
  passes the item names retrieval just surfaced as candidate targets, and the
  model connects new facts to them — see
  [Host Integration](/guide/host-integration).
- **You**, in any text editor. Links are plain text in the content; the next
  `rebuild()` (or process restart) picks them up.

## Parsing rules

Link parsing is deliberately liberal, because hand-edited files must never
crash a read:

- The pattern is `[[category:name]]` — category is everything up to the
  **first** colon; neither part may contain `[`, `]`, a newline, or another
  colon.
- Whitespace around either part is trimmed; malformed or empty links are
  silently ignored by the parser (not an error).
- Item names are kept colon-free **by construction**: `sanitize_item_name`
  rejects `[[`, `]]`, `:`, `|`, `#` at write time, which keeps every link
  unambiguous and greppable.

```python
from wikimem import parse_wiki_links

parse_wiki_links("… [[daily_life:beach-trip-plan]] and [[broken link …")
# [WikiLink(category='daily_life', name='beach-trip-plan')]
```

## Dangling links

Files are user-editable, so a link's target can be renamed or deleted at any
time. wikimem treats that as normal life, not corruption:

- Expansion skips the missing target and keeps going.
- The unresolved address is reported in
  [`RetrievalResult.unresolved_links`](/reference/api#retrievalresult), so a
  host (or the future `wikimem graph` CLI) can surface it for repair.

## Scope: one hop, by design

Expansion is exactly one hop — hits pull in their direct link targets, and
those targets do **not** pull in theirs; multi-hop chains surface hop-by-hop
across turns as the conversation touches them. One hop keeps the injected
context proportional to the hit count, the token cost predictable, and the
behavior explainable ("this item is here because that hit links to it"). The
same reasoning applies to the token budget's
[prefix-cut semantics](/guide/retrieval#_4-token-budget).
