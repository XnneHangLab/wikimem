# Writing the diary

The [diary](/reference/file-format#diary-files-diary) is the *event* layer — one
vivid paragraph per moment, in the character's voice. wikimem **stores** those
entries ([`Diary.append`](/reference/api#diary)); it never writes them. What to
write, and how, is your host's memorize step — an LLM call you own.

This page is the **reference prompt** for guiding that call, plus the smallest
way to wire it up. The same text ships as
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
