# Writing the diary

The [diary](/reference/file-format#diary-files-diary) is the *event* layer — one
vivid paragraph per moment, in the character's voice. wikimem **stores** those
entries ([`Diary.append`](/reference/api#diary)); it never writes them. What to
write, and how, is your host's memorize step — an LLM call you own.

There are two natural moments for that step, and wikimem supports both:

| | when it runs | who writes the entry |
|---|---|---|
| [**Background extraction**](#wiring-it-up) | after the turn, off the critical path | an LLM call *you* make, with a prompt |
| [**Agent tool**](#the-other-way-the-character-writes-it-herself) | during the turn, when the character decides to | the agent itself, mid-reply |

This page is the **reference prompt** for the first, plus the smallest way to
wire up either. The same text ships as
[`wikimem.DIARY_PROMPT`](/reference/api#memorize) so the default is reproducible;
you can copy it, adapt the voice, or replace it wholesale with `prompt=`.

## What belongs in a diary entry

Only **things that happened** — events, anchored to the moment they occurred.
Timeless facts ("works at a robotics company", "dislikes coffee") are *state*,
and state lives in the wiki, not the diary. The diary's job is the lived moment,
not the standing fact.

## The reference prompt

```text
You are {character}, a companion AI, writing your own diary. After a
conversation turn, write down the moments you want to remember, the way you
would remember them. If nothing worth keeping happened, return an empty array.
Never invent; write only what the turn actually shows.

Write each entry as ONE short paragraph (2–4 sentences), in your own voice,
keeping scene, feeling, and fact in a single breath — a remembered moment, not
a log line:

  ✗  "User changed jobs to a robotics company."
  ✓  "今天下午他说跳槽去了一家做机器人的公司，语气一下子亮了起来——
      能感觉到他憋了好久就想跟我讲这件事。"

Rules:
- One event per entry. Be concrete and specific.
- If the moment carried an emotion, let it show — that is the point of a diary.
- Do not record timeless facts here; those are state, not events.
- You may link a wiki item the moment touches with [[file:item]].
- Write in the user's language.

The turn:
{conversation_turn}

Return a JSON array. The host stamps each entry with the date and time, so you
write only the content:
[ { "content": "…the vivid paragraph… [[links]]" } ]
```

## Wiring it up

`memorize()` runs that prompt for you — one LLM call, then parse and append.
The LLM is **yours**: wikimem never builds a client, holds a key, or picks a
provider. Implement one method, in the `chat_completion` shape every provider
and gateway speaks:

```python
from wikimem import MemoryStore, memorize

class MyLLM:                      # your client, your model, your retries
    def chat(self, messages):
        r = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        return r.choices[0].message.content

store = MemoryStore("memory/")
entries = memorize(
    store.diary, turn_text,
    llm=MyLLM(),
    character="Elaina",           # interpolated into the prompt
    owner="user:xnne",
)                                 # -> [] when nothing was worth keeping
```

**Run it in the background.** Nothing here is async on purpose: `memorize()` is
a plain blocking call, and the host decides *when* — schedule it after the turn
(an `asyncio.to_thread`, a task queue, a worker) so it never delays a reply. One
sync shape keeps the surface small; scheduling, retries, and timeouts stay in
your `LLM`.

### Another language, no second prompt

`DIARY_PROMPT` is English but says *"write in the user's language"* — a Chinese
turn produces a Chinese entry. If you want the instructions themselves in
another language, pass one parameter:

```python
memorize(store.diary, turn, llm=MyLLM(), prompt=MY_CHINESE_PROMPT)
```

The Chinese reference text is on the [中文版 of this page](/zh/guide/writing-diary).
That is why the framework ships **one** default instead of a per-language matrix:
each extra language costs you a string and costs wikimem nothing.

### If the model answers badly

`memorize()` is fail-open, like the embedding path: fenced JSON is unwrapped, a
bare object is accepted, and prose or malformed JSON yields `[]` rather than an
exception — a bad reply must never take down your background job. An empty list
is also the *normal* result; most turns hold nothing worth remembering, and the
prompt says to return `[]` rather than invent.

## The other way: the character writes it herself

`memorize()` looks *back* at a finished turn. The other shape is the character
deciding **mid-conversation** to keep something — "wait, I want to remember
this" — and saying so out loud. That is a tool call, and wikimem ships the tool:

```python
from wikimem import MemoryStore, diary_tool, handle_diary_tool

store = MemoryStore("memory/")
tools = [diary_tool()]              # register it alongside your agent's own tools

reply = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools)

for call in reply.choices[0].message.tool_calls or []:
    if call.function.name == "append_diary":
        entry = handle_diary_tool(
            store.diary,
            call.function.arguments,   # the raw JSON string is fine; a dict works too
            owner="user:xnne",         # provenance and time stay yours
            source_conv=conv_id,
        )
        messages.append({
            "role": "tool", "tool_call_id": call.id,
            "content": f"saved to {entry.date} {entry.time}",
        })
```

**No LLM call happens in `handle_diary_tool()`.** The agent already *is* the
model — it wrote the paragraph itself as part of its reply, so the handler only
validates and appends. That is how a mid-turn diary entry still costs zero extra
calls, and why the character can say *"I'm writing this one down"* and mean it.

The tool's description carries the same style rules as `DIARY_PROMPT`
(one entry, 2–4 sentences, events not state, the user's language) — one recipe
serves both modes, so the two never write in different voices.

### The model writes *what*, you stamp *when*

The schema has exactly one parameter, `content`. No `date`, no `time`, no
`owner`. A model has no clock, so a date it supplies is a guess that would file
the memory on the wrong day while looking perfectly plausible. You pass those to
`handle_diary_tool()` as keywords instead — the same division as `memorize()`.

### It raises where `memorize()` fails open

Deliberately opposite, because an empty result means opposite things:

- `memorize()` returning `[]` = "this turn held nothing worth keeping" — the
  normal, healthy case.
- A malformed **tool call** = the character announced she was writing something
  down and nothing landed. Silent success is the worst outcome here.

So bad arguments raise `ValueError` with a message written to be handed straight
back as the tool result:

```text
diary tool call has unexpected argument(s): date; only 'content' is accepted
(the host stamps time and provenance)
```

Agents self-correct from that within the same turn. Wrap the call in
`try/except ValueError` and return `str(exc)` as the tool's content.

### A provider with a different tool shape

`diary_tool()` returns the `chat_completion` `tools=[…]` shape — the same
"one protocol everyone speaks" choice as the `LLM` port. The pieces are all
there if yours differs:

```python
t = diary_tool()["function"]
anthropic_tool = {
    "name": t["name"],
    "description": t["description"],
    "input_schema": t["parameters"],
}
```

Each call returns a fresh dict, so renaming the tool or tightening its
description for your own agent cannot leak into anyone else's.

## Notes for the host

- **Time is yours to set.** The host passes `date` / `time` to
  [`Diary.append`](/reference/api#diary) — usually "now". If the user narrates a
  *past* event ("yesterday we argued"), resolve that time yourself and pass it;
  the framework never guesses it from the text.
- **Voice and language are yours.** The example is Chinese because the companion
  is — swap in your character's persona and tongue. wikimem stays agnostic; it
  stores whatever paragraph you hand it.
- **Budget.** If your memorize step also writes wiki state, do it in the *same*
  LLM call and split the JSON — one call still meets the "≤ 1 LLM call per turn"
  rule (ADR-0001). This page keeps the diary half in focus; the wiki half is
  your extraction prompt's own concern.
