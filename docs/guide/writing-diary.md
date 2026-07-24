# Writing the diary

The [diary](/reference/file-format#diary-files-diary) is the *event* layer — one
vivid paragraph per moment, in the character's voice. wikimem **stores** those
entries ([`Diary.append`](/reference/api#diary)); it never writes them. What to
write, and how, is your host's memorize step — an LLM call you own.

This page is a **reference prompt** for guiding that call: a good default, not
shipped as code (prompts should evolve freely, not on a version boundary). Copy
it, adapt the voice and language to your character, and wire it into your own
extraction step.

## What belongs in a diary entry

Only **things that happened** — events, anchored to the moment they occurred.
Timeless facts ("works at a robotics company", "dislikes coffee") are *state*,
and state lives in the wiki, not the diary. The diary's job is the lived moment,
not the standing fact.

## The reference prompt

```text
You are the diary-keeper behind {character}, a companion AI. After a
conversation turn, write down the moments worth remembering — as {character}
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
- You may link a wiki item the moment touches with [[category:item]].
- Write in the user's language.

The turn:
{conversation_turn}

Return a JSON array. The host stamps each entry with the date and time, so you
write only the content:
[ { "content": "…the vivid paragraph… [[links]]" } ]
```

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
