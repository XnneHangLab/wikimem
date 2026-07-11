# Host Integration

wikimem is a library, not a framework: it never calls an LLM and has no event
loop. The **host** (your agent) wires it into the conversation at two points,
under one contract fixed by ADR-0001:

| Hook | When | Cost | Failure mode |
|---|---|---|---|
| **Retrieve** | before each turn | 0 LLM calls, synchronous, budgeted | fail-open: inject nothing |
| **Memorize** | after each turn | ≤ 1 LLM call, asynchronous | fail-open: skip this turn |

The reference implementation is the
[XnneHangLab wikimem plugin](https://github.com/XnneHangLab/XnneHangLab/tree/dev/src/lab/plugins/wikimem)
(~240 lines including config). The patterns below are distilled from it.

## Before the turn: retrieve and inject

```python
async def on_before_turn(self, user_text: str) -> str | None:
    try:
        result = self.index.retrieve(
            user_text, limit=10, budget_tokens=800,
        )
        # remember what surfaced — these become link targets at memorize time
        self.related_names = [f"{r.item.category}:{r.item.name}" for r in result.items]
        if not result.items:
            return None
        return "\n".join(
            f"- [{r.item.category}:{r.item.name}] {r.item.content}"
            for r in result.items
        )
    except Exception:
        return None   # fail-open: a broken memory system must not break the chat
```

Choices worth copying:

- **Label each injected item with its `category:name` address.** The model
  sees stable addresses it can refer to, and the extraction step can link to
  them (`[[category:name]]`) without guessing.
- **Keep the budget in host hands.** `budget_tokens` is the knob that decides
  how much of the prompt memory may occupy; retrieval guarantees it is
  respected and tells you (`budget_used`) what it spent.
- **Wrap it fail-open.** `retrieve` itself never raises for degraded optional
  paths, but the host-side wrapper catches everything else (bad paths,
  permissions) — a memory bug costs one turn of recall, never the turn.

## After the turn: memorize in the background

The hook must return immediately; extraction runs as a background task:

```python
async def on_after_turn(self, user_text: str, assistant_text: str) -> None:
    task = asyncio.create_task(self._memorize(user_text, assistant_text))
    self._pending.add(task)                       # keep a strong reference
    task.add_done_callback(self._pending.discard)

async def flush(self) -> None:
    """Await pending extractions — call on graceful shutdown and in tests."""
    if self._pending:
        await asyncio.gather(*self._pending, return_exceptions=True)
```

Inside `_memorize`: one LLM call that turns the turn into zero or more items,
then plain `store.add` calls. No LLM output is trusted:

- **Parse tolerantly.** Find the outermost `[...]` in the response and
  `json.loads` it; anything malformed → memorize nothing this turn.
- **Validate per item, not per batch.** `store.add` raises `ValueError` for
  an invalid category slug or reserved characters in a name — skip that item
  and keep the rest.
- **Cap items per turn** (the reference plugin uses 8) so one chatty
  extraction can't flood the store.

## The extraction prompt

The single prompt does double duty — extract facts *and* wire the graph. The
rules that earn their place (full text in the reference plugin, design
borrowed from memU per lab ADR-0002):

- **Each item self-contained** — readable on its own, same language as the
  conversation.
- **Exclude the ephemeral** — weather, greetings, in-progress task state.
- **Attribute correctly** — the user's facts are the user's; only the
  assistant's own commitments are the assistant's.
- **`category` is a lowercase slug** (suggest a base set: `preferences`,
  `daily_life`, `profile`, `event`, `knowledge`, …; new ones allowed) —
  matching wikimem's category validation.
- **`name` short and stable**, without `: | # [[ ]]` — matching
  `sanitize_item_name`.
- **Link, don't repeat**: pass the categories that exist
  (`store.categories()`) and the items retrieval surfaced this turn
  (`related_names` from above) as candidate link targets, and have the model
  write `[[category:name]]` inline when a new fact relates to one. This is
  the moment the wiki-link graph gets built.
- **Empty is a valid answer**: no memorable facts → `[]`.

## Same-named items are updates

`store.add("preferences", "coffee", "...")` **replaces** an existing
`preferences:coffee` — the extraction LLM updating a fact it has seen before
is the natural update path (the journal records it as `update`, not `add`).
Stable, name-like item names make this work; timestamps or serial numbers in
names would turn every update into a duplicate.

## Deployment notes

- **One process, one store.** Writes are atomic per category file, but the
  revision counter that keeps the index fresh is in-process state. Multiple
  writer processes on one directory is not a supported topology.
- **Restart is free.** The BM25 index rebuilds at startup from the files; the
  vector cache (if any) syncs incrementally by content hash. There is no
  warm-up state to preserve.
- **Watch two signals** in host logs: `embedding_used` (how often fusion
  actually ran) and `unresolved_links` (dangling links worth repairing).
