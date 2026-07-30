"""Memorize — the framework's half of both ADR-0005 modes, with no network.

Mode A's LLM is a stub; mode B needs no LLM at all (the agent is the LLM). What
is pinned here is the framework's side of the contract: prompt assembly,
tolerant parsing, append, fail-open — and, for the tool, the opposite choice of
refusing to swallow a malformed call.
"""

import json
from pathlib import Path

import pytest

from wikimem import (
    DIARY_PROMPT,
    DIARY_TOOL_DESCRIPTION,
    Diary,
    diary_tool,
    handle_diary_tool,
    memorize,
)
from wikimem.memorize import parse_entries


class FakeLLM:
    """Records the messages it was handed and replays a canned reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.reply


@pytest.fixture()
def diary(tmp_path: Path) -> Diary:
    return Diary(tmp_path / "memory")


# ------------------------------------------------------------------ happy path


def test_memorize_appends_entry_and_calls_llm_once(diary: Diary):
    llm = FakeLLM('[{"content": "今天他说换了工作，语气很兴奋。"}]')
    entries = memorize(diary, "我今天换工作了！", llm=llm, date="2026-07-24", time="14:30")

    assert len(llm.calls) == 1  # exactly one LLM call
    assert [e.content for e in entries] == ["今天他说换了工作，语气很兴奋。"]
    # and it is on disk, through the normal append path
    assert [e.content for e in diary.day("2026-07-24")] == ["今天他说换了工作，语气很兴奋。"]


def test_prompt_is_system_plus_user_turn(diary: Diary):
    llm = FakeLLM("[]")
    memorize(diary, "我今天换工作了！", llm=llm, character="Elaina")

    (messages,) = llm.calls
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Elaina" in messages[0]["content"]  # persona interpolated
    assert "{character}" not in messages[0]["content"]  # no leftover placeholder
    assert messages[1]["content"] == "我今天换工作了！"


def test_custom_prompt_overrides_default(diary: Diary):
    llm = FakeLLM("[]")
    memorize(diary, "turn", llm=llm, prompt="你是 {character} 的日记记录者。", character="伊蕾娜")

    system = llm.calls[0][0]["content"]
    assert system == "你是 伊蕾娜 的日记记录者。"


def test_provenance_and_multiple_entries(diary: Diary):
    llm = FakeLLM('[{"content": "第一件事。"}, {"content": "第二件事。"}]')
    entries = memorize(
        diary,
        "turn",
        llm=llm,
        owner="user:xnne",
        source_conv="conv_1",
        date="2026-07-24",
        time="09:00",
    )
    assert len(entries) == 2
    assert all(e.owner == "user:xnne" and e.source_conv == "conv_1" for e in entries)
    # both land in the same day file — a minute may repeat (append-only)
    assert len(diary.day("2026-07-24")) == 2


# ------------------------------------------------- nothing-to-remember & fail-open


def test_empty_array_writes_nothing(diary: Diary):
    # The healthy common case: most turns hold nothing worth keeping.
    assert memorize(diary, "在吗", llm=FakeLLM("[]")) == []
    assert diary.dates() == []


@pytest.mark.parametrize(
    "reply",
    [
        "",  # empty reply
        "I could not find anything.",  # prose, not JSON
        "{broken json",  # malformed
        '[{"content": "   "}]',  # blank content
        '["", null, 5]',  # junk rows
    ],
)
def test_unusable_reply_is_fail_open(diary: Diary, reply: str):
    assert memorize(diary, "turn", llm=FakeLLM(reply)) == []
    assert diary.dates() == []  # nothing written


def test_append_errors_propagate(diary: Diary):
    """A write failure must reach the host, not be swallowed.

    fail-open covers the *model's* output, not the *disk*: if the store cannot be
    written (full disk, no permission), the host's background job has to learn
    about it. Pinned so nobody later wraps the append in a bare ``except``.
    """
    llm = FakeLLM('[{"content": "会写失败的一条。"}]')
    with pytest.raises(ValueError):
        memorize(diary, "turn", llm=llm, date="not-a-date")


# ---------------------------------------------------------------- parse_entries


def test_parse_strips_code_fences():
    assert parse_entries('```json\n[{"content": "去了海边。"}]\n```') == ["去了海边。"]
    assert parse_entries('```\n[{"content": "x"}]\n```') == ["x"]


def test_parse_accepts_a_lone_object_as_one_entry():
    # A missing array wrapper is a packaging slip; the {"content": …} shape is intact.
    assert parse_entries('{"content": "只有一条。"}') == ["只有一条。"]


def test_parse_rejects_entries_that_are_not_content_objects():
    # A bare-string array means the model ignored the required structure — we do
    # not guess at it, or malformed memories get through. Mixed replies keep only
    # the well-formed rows.
    assert parse_entries('["直接给字符串"]') == []
    assert parse_entries('[{"content": "好的"}, "裸字符串", 5, null]') == ["好的"]


def test_parse_trims_and_drops_blanks():
    assert parse_entries('[{"content": "  padded  "}, {"content": ""}]') == ["padded"]


# ------------------------------------------------------------------- the prompt


def test_default_prompt_states_the_core_rules():
    assert "{character}" in DIARY_PROMPT  # host interpolates the persona
    lowered = DIARY_PROMPT.lower()
    assert "happened" in lowered  # events, not state
    assert "user's language" in lowered  # output language follows the turn
    assert "[]" in DIARY_PROMPT  # the nothing-to-remember escape hatch


# ============================================================ mode B: agent tool


@pytest.fixture()
def tool_args() -> str:
    """Arguments in the shape OpenAI-style providers deliver them: a JSON string."""
    return json.dumps({"content": "他今天把那只流浪猫抱回了家，笑得像个孩子。"}, ensure_ascii=False)


# ------------------------------------------------------------------ the schema


def test_schema_exposes_content_only():
    """The model writes *what*; the host stamps *when* — same split as mode A.

    Pinned deliberately: a `date` property here would let the model file a
    memory on a day it merely guessed at, and be wrong without anyone noticing.
    """
    params = diary_tool()["function"]["parameters"]
    assert set(params["properties"]) == {"content"}
    assert params["required"] == ["content"]
    assert params["additionalProperties"] is False


def test_schema_is_chat_completion_tool_shaped():
    tool = diary_tool()
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "append_diary"
    assert tool["function"]["description"] == DIARY_TOOL_DESCRIPTION
    # JSON-serializable, since it is handed straight to a provider.
    assert json.loads(json.dumps(tool)) == tool


def test_each_call_returns_an_independent_schema():
    """A host editing the returned dict must not corrupt it for everyone else."""
    first = diary_tool()
    first["function"]["name"] = "remember_this"
    first["function"]["parameters"]["properties"]["content"]["description"] = "changed"

    second = diary_tool()
    assert second["function"]["name"] == "append_diary"
    assert second["function"]["parameters"]["properties"]["content"]["description"] != "changed"


def test_tool_description_shares_the_prompt_style_rules():
    """ADR-0005 §4: one reference recipe serves both modes.

    Two hand-maintained copies of the style rules would drift — and drift here is
    invisible, showing up only as the two modes writing in different voices. So
    every rule line is required to be present in both, verbatim.
    """
    rules = [line for line in DIARY_TOOL_DESCRIPTION.splitlines() if line.startswith("- ")]
    assert len(rules) >= 5
    shared = [r for r in rules if "Do not call this tool" not in r]  # mode-B specific
    for rule in shared:
        assert rule in DIARY_PROMPT, f"rule drifted from DIARY_PROMPT: {rule}"


def test_tool_description_tells_the_model_not_to_stamp_time():
    # The counterpart of the schema having no date/time: say why, or the model
    # tries to put the timestamp in the content.
    assert "stamped for you" in DIARY_TOOL_DESCRIPTION


# ----------------------------------------------------------------- the handler


def test_handle_appends_from_a_json_string(diary: Diary, tool_args: str):
    entry = handle_diary_tool(diary, tool_args, date="2026-07-30", time="21:15")

    assert entry.content.startswith("他今天把那只流浪猫抱回了家")
    assert (entry.date, entry.time) == ("2026-07-30", "21:15")
    # and it went through the normal append path, onto disk
    assert [e.content for e in diary.day("2026-07-30")] == [entry.content]


def test_handle_accepts_an_already_parsed_dict(diary: Diary):
    # Anthropic-style providers hand over `input` already parsed.
    entry = handle_diary_tool(
        diary, {"content": "散步时下了点小雨。"}, date="2026-07-30", time="18:00"
    )
    assert entry.content == "散步时下了点小雨。"


def test_handle_forwards_provenance(diary: Diary, tool_args: str):
    entry = handle_diary_tool(
        diary, tool_args, owner="user:xnne", source_conv="conv_7", date="2026-07-30", time="21:15"
    )
    assert (entry.owner, entry.source_conv) == ("user:xnne", "conv_7")
    assert diary.day("2026-07-30")[0].owner == "user:xnne"


def test_handle_makes_no_llm_call(diary: Diary, tool_args: str):
    """Mode B takes no `llm` at all — the agent already wrote the content.

    ADR-0005 §3/§4: this is what keeps "≤1 LLM call per turn" true when the
    character writes a diary entry mid-conversation.
    """
    import inspect

    assert "llm" not in inspect.signature(handle_diary_tool).parameters


# ------------------------------------------------- malformed calls: loud, not silent


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "must be a JSON object"),
        ("null", "must be a JSON object"),
        ('{"text": "写错了字段名"}', "unexpected argument"),
        ('{"content": 5}', "missing a string"),
        ("{}", "missing a string"),
    ],
)
def test_malformed_call_raises_with_a_message_for_the_agent(diary: Diary, args: str, expected: str):
    """The opposite of mode A's fail-open, on purpose.

    Mode A returning `[]` means "nothing worth keeping" — healthy. A broken tool
    call means the character said "I'll write that down" and nothing landed. The
    message is written to be handed back as the tool result so the agent can fix
    itself in the same turn.
    """
    with pytest.raises(ValueError, match=expected):
        handle_diary_tool(diary, args)
    assert diary.dates() == []  # and nothing was written


def test_extra_argument_is_refused_rather_than_dropped(diary: Diary):
    """A model-supplied `date` must never be silently ignored.

    Dropping it would file the entry under *today* while the model believed it
    filed it under yesterday — wrong, plausible, and invisible. The schema says
    additionalProperties: false, so this is the model ignoring the schema.
    """
    with pytest.raises(ValueError, match="date"):
        handle_diary_tool(diary, {"content": "昨天的事。", "date": "2026-07-29"})
    assert diary.dates() == []


def test_blank_content_is_refused_by_append(diary: Diary):
    # Diary.append already owns this rule; the handler must not duplicate or
    # swallow it.
    with pytest.raises(ValueError, match="empty"):
        handle_diary_tool(diary, {"content": "   "})
