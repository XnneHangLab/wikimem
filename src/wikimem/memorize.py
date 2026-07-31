"""Memorize: turn a conversation into diary entries (ADR-0005).

The framework owns the **recipe** — prompt, parsing, validation, append — and the
host owns the **LLM**. wikimem never constructs a client, holds a key, or picks a
provider, in either of the two modes the ADR defines:

* **Mode A — background extraction** (:func:`memorize`). You pass something with
  a ``chat()`` method and it is called exactly once, after the turn, off the
  conversation's critical path. The convenience of "one function that produces
  memory", with the LLM injected.
* **Mode B — agent tool** (:func:`diary_tool` / :func:`handle_diary_tool`). The
  character decides *mid-turn* to write something down and calls a tool to do
  it. There is **no LLM call here at all**: the agent already is the LLM, so it
  writes the content itself and wikimem only persists it.

Either way the framework makes zero LLM calls of its own.

Mode A is deliberately minimal, in one shape only:

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
from .models import DiaryItem

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
- You may reference a related memory inline with [[file:item]].
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
) -> list[DiaryItem]:
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


# --------------------------------------------------------------- mode B: agent tool

#: Tool description for mode B, carrying the *same* style rules as
#: :data:`DIARY_PROMPT` — ADR-0005 §4: one reference recipe serves both modes.
#: The five ``-`` rules below are byte-identical to the prompt's (a test pins
#: that); only the framing differs, because the two modes ask for different
#: things: mode A extracts from a finished turn and answers with JSON, mode B is
#: a deliberate act by the character mid-conversation.
DIARY_TOOL_DESCRIPTION = """\
Write one moment to your diary. Call this when something in the conversation is
worth remembering and you have decided to remember it — this is you choosing to
keep it, not a background chore.

Write the entry as ONE short paragraph (2-4 sentences), in your own voice, keeping
scene, feeling, and fact in a single breath — a remembered moment, not a log line:

  BAD:  "User changed jobs to a robotics company."
  GOOD: "今天下午他说跳槽去了一家做机器人的公司，语气一下子亮了起来——
         能感觉到他憋了好久就想跟我讲这件事。"

Rules:
- Only things that HAPPENED. Timeless facts are state, and state is not diary.
- One event per entry. Be concrete and specific.
- If the moment carried an emotion, let it show — that is the point of a diary.
- You may reference a related memory inline with [[file:item]].
- Write in the user's language.
- Nothing worth keeping? Do not call this tool. Never invent what did not happen.

The date and time are stamped for you — write only the content.\
"""

#: The one parameter the model may set. Time and provenance are deliberately
#: absent: the host stamps *when*, the model only writes *what* (same division as
#: mode A). Letting the model pass a date would make a wrong day silently
#: plausible, and it has no clock to be right with.
_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": "The diary entry: one short paragraph, in your own voice.",
        }
    },
    "required": ["content"],
    "additionalProperties": False,
}


def diary_tool() -> dict[str, Any]:
    """A function-call schema for ``append_diary(content)`` — mode B.

    Register it with your agent alongside its other tools, and route the call to
    :func:`handle_diary_tool`::

        tools = [diary_tool(), ...]

    Shaped for the ``chat_completion`` ``tools=[...]`` array, matching mode A's
    choice of the protocol every provider and gateway speaks. Hosts on a
    different tool shape reshape it themselves — the parts are all here::

        t = diary_tool()["function"]
        anthropic_tool = {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }

    A fresh dict every call, so a host that edits the returned schema (renaming
    the tool, tightening the description) cannot mutate it for everyone else.
    """
    return {
        "type": "function",
        "function": {
            "name": "append_diary",
            "description": DIARY_TOOL_DESCRIPTION,
            # Copied per call for the same reason the outer dict is fresh.
            "parameters": json.loads(json.dumps(_TOOL_PARAMETERS)),
        },
    }


def handle_diary_tool(
    diary: Diary,
    args: str | dict[str, Any],
    **append_kwargs: Any,
) -> DiaryItem:
    """Persist a mode-B tool call and return the stored entry.

    ``args`` is the model's arguments in whichever form your provider hands them
    over: a JSON **string** (``tool_call.function.arguments``) or an already
    parsed **dict**. Anything the host knows better than the model — ``date`` /
    ``time`` / ``ts`` / ``owner`` / ``source_conv`` — goes in as a keyword and is
    forwarded to :meth:`Diary.append`::

        entry = handle_diary_tool(store.diary, call.function.arguments,
                                  owner="user:xnne", source_conv=conv_id)

    **Raises rather than fails open**, unlike mode A's :func:`memorize`. The two
    look similar but mean opposite things: mode A's empty result says "this turn
    held nothing worth keeping", the healthy common case. A malformed *tool call*
    says the character tried to write something down and it did not land — the
    exact silent failure worth refusing to have. Hand the message back to the
    agent as the tool result and it can correct itself in the same turn.

    Every malformed ``args`` raises ``ValueError`` — never a second exception
    type — so one ``except ValueError`` in the agent loop covers all of them::

        try:
            entry = handle_diary_tool(store.diary, call.function.arguments)
        except ValueError as exc:
            tool_result = str(exc)      # the agent reads this and retries

    (A mistyped ``**append_kwargs`` still raises ``TypeError``, but that is the
    *host's* own bug, not the model's, and should surface as one.)
    """
    if isinstance(args, str):
        try:
            parsed: Any = json.loads(args)
        except ValueError as exc:
            raise ValueError(f"diary tool arguments are not valid JSON: {exc}") from exc
    else:
        parsed = args
    # On the two TRY004 suppressions below: these stay ValueError, not TypeError,
    # because the value came off the wire from a model rather than from a
    # caller's code. One exception type for every malformed call is the point —
    # the host wraps this in a single `except ValueError` and hands the message
    # back to the agent; a second type would slip past that clause and take the
    # agent loop down with it.
    if not isinstance(parsed, dict):
        raise ValueError(  # noqa: TRY004 - malformed model output, not a caller type error
            f"diary tool arguments must be a JSON object, got {type(parsed).__name__}"
        )

    # The schema declares exactly one property and forbids others, so an extra
    # key means the model believes it set something we are about to drop — a
    # date it "remembered" would silently file the entry on the wrong day.
    #
    # ``str(k)`` before sorting/joining is load-bearing, not defensive noise: a
    # host-built dict may hold non-string keys, and then ``sorted`` raises
    # TypeError on mixed types while ``join`` raises it on any non-str. Either
    # would escape the caller's ``except ValueError`` and take the agent loop
    # down — the one failure this function exists to prevent.
    unexpected = sorted(str(k) for k in set(parsed) - {"content"})
    if unexpected:
        raise ValueError(
            f"diary tool call has unexpected argument(s): {', '.join(unexpected)}; "
            "only 'content' is accepted (the host stamps time and provenance)"
        )

    content = parsed.get("content")
    if not isinstance(content, str):
        raise ValueError(  # noqa: TRY004 - see above
            "diary tool call is missing a string 'content'"
        )
    return diary.append(content, **append_kwargs)
