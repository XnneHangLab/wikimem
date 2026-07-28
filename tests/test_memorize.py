"""Memorize — one injected, chat_completion-shaped LLM call (ADR-0005, mode A).

The LLM is a stub: these pin the framework's half of the contract (prompt
assembly, tolerant parsing, append, fail-open) without a network call.
"""

from pathlib import Path

import pytest

from wikimem import DIARY_PROMPT, Diary, memorize
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
