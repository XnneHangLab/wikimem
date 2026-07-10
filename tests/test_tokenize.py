import pytest

from wikimem import est_tokens, tokenize


def test_ascii_words_lowercased():
    assert tokenize("Hello WORLD v2", use_jieba=False) == ["hello", "world", "v2"]


def test_cjk_bigrams():
    assert tokenize("喜欢海边", use_jieba=False) == ["喜欢", "欢海", "海边"]


def test_single_cjk_char():
    assert tokenize("海", use_jieba=False) == ["海"]


def test_mixed_text():
    tokens = tokenize("我用 Python 写 TTS", use_jieba=False)
    assert "python" in tokens and "tts" in tokens and "我用" in tokens


def test_punctuation_splits_cjk_runs():
    # 逗号切断 run，不产生跨标点的假 bigram
    assert tokenize("喜欢，海边", use_jieba=False) == ["喜欢", "海边"]


def test_jieba_path_when_installed():
    pytest.importorskip("jieba")
    tokens = tokenize("我喜欢去海边散步", use_jieba=True)
    assert "海边" in tokens


def test_est_tokens_heuristic():
    assert est_tokens("hello world") == 2
    assert est_tokens("喜欢海边") == 4
    assert est_tokens("用 Python 写工具") == 5  # 1 word + 4 CJK chars (用/写/工/具)
