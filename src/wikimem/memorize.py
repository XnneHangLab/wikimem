"""Memorize: turn a conversation turn into diary entries (ADR-0005, mode A).

The framework owns the **recipe** — prompt, parsing, validation, append — and the
host owns the **LLM**. wikimem never constructs a client, holds a key, or picks a
provider: you pass something with a ``chat()`` method and it is called exactly
once. That keeps the "framework makes zero LLM calls of its own" constraint
intact while giving hosts the convenience of one function that produces memory.

Deliberately minimal, in one shape only:

* **Sync.** memorize is a background job on the host's side already (it must
  never block a conversation turn), so async buys nothing and doubles the API.
* **``chat_completion``-shaped.** A ``messages`` list in, assistant text out —
  the one protocol every provider and gateway speaks. No streaming, no tools,
  no ``responses``-style typed items: supporting N protocols would cost N times
  the maintenance for a single small call.

Anything else — which model, retries, timeouts, async scheduling, cost caps —
belongs to the host's ``LLM`` implementation, not here.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from .diary import Diary
from .models import DiaryEntry

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

#: The bundled reference prompt (ADR-0005). English instructions, but the entry
#: is written in the *conversation's* language — so a Chinese turn yields a
#: Chinese entry without a second prompt to maintain. Pass ``prompt=`` to
#: override wholesale (e.g. the Chinese variant in the docs); that one parameter
#: is why the framework never needs a per-language matrix.
DIARY_PROMPT = """\
You are {character}, a companion AI, writing your own diary. Given a conversation
turn, write down the moments you want to remember, the way you would remember them.

Write each entry as ONE short paragraph (2-4 sentences), in your own voice, keeping
scene, feeling, and fact in a single breath — a remembered moment, not a log line:

  BAD:  "User changed jobs to a robotics company."
  GOOD: "今天下午他说跳槽去了一家做机器人的公司，语气一下子亮了起来——
         能感觉到他憋了好久就想跟我讲这件事。"

Rules:
- Only things that HAPPENED. Timeless facts are state, and state is not diary.
- One event per entry. Be concrete and specific.
- If the moment carried an emotion, let it show — that is the point of a diary.
- You may reference a related memory inline with [[category:item]].
- Write in the user's language.
- Nothing worth keeping? Return []. Never invent what the turn does not show.

Return ONLY a JSON array, no prose around it:
[{{"content": "…the vivid paragraph…"}}]\
"""


class LLM(Protocol):
    """A ``chat_completion``-shaped call: messages in, assistant text out.

    Implement it over whatever client the host already has::

        class MyLLM:
            def chat(self, messages):
                r = client.chat.completions.create(model="…", messages=messages)
                return r.choices[0].message.content
    """

    def chat(self, messages: list[dict[str, str]]) -> str: ...


def parse_entries(raw: str) -> list[str]:
    """Extract entry contents from a model reply — never raises.

    Tolerant of *packaging*, strict about *shape*. Models routinely wrap JSON in
    ``` fences or hand back a lone ``{...}`` instead of a one-item array, so both
    are unwrapped. But an entry must still be an object with a ``content``
    string: a reply that ignores that structure ignored the prompt, and guessing
    at what it meant would only let malformed memories through. Anything
    unusable yields ``[]`` (fail-open, like the embedding path) — a bad reply
    must not take down the host's background job.
    """
    text = _FENCE_RE.sub("", raw.strip())
    try:
        data: Any = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        content = row.get("content")
        if isinstance(content, str) and content.strip():
            out.append(content.strip())
    return out


def memorize(
    diary: Diary,
    turn: str,
    *,
    llm: LLM,
    character: str = "the assistant",
    prompt: str | None = None,
    owner: str | None = None,
    source_conv: str | None = None,
    **append_kwargs: Any,
) -> list[DiaryEntry]:
    """Write the turn's memorable moments to the diary. **One** LLM call.

    Returns the appended entries — often empty, which is the healthy case: most
    turns hold nothing worth keeping, and the prompt says to return ``[]`` rather
    than invent. A reply that cannot be parsed also yields ``[]``.

    ``prompt`` replaces the bundled :data:`DIARY_PROMPT` (it is ``.format``-ed
    with ``character``); ``owner`` / ``source_conv`` and any extra keyword go to
    :meth:`Diary.append`, so the caller keeps control of provenance and time —
    the host stamps *when*, the model only writes *what*.
    """
    system = (prompt or DIARY_PROMPT).format(character=character)
    reply = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": turn}])
    return [
        diary.append(content, owner=owner, source_conv=source_conv, **append_kwargs)
        for content in parse_entries(reply or "")
    ]
