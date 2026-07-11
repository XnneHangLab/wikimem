"""Tokenization for retrieval.

Zero-dependency default: ASCII/latin words (lowercased) plus character
bigrams for CJK runs — good enough for keyword recall without a segmenter.
When the optional ``[zh]`` extra is installed, CJK runs go through jieba
instead (better Chinese recall). jieba is lazy-imported so core startup
never pays for it.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")
# CJK unified ideographs (+ ext A) and kana.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]+")

_jieba_checked = False
_jieba = None


def _load_jieba():
    global _jieba_checked, _jieba
    if not _jieba_checked:
        _jieba_checked = True
        try:
            import jieba  # ty: ignore[unresolved-import]  # Lazy-import: optional [zh] extra

            jieba.setLogLevel(60)  # silence init banner
            _jieba = jieba
        except ImportError:
            _jieba = None
    return _jieba


def _cjk_tokens(run: str, use_jieba: bool) -> list[str]:
    if use_jieba:
        jieba = _load_jieba()
        if jieba is not None:
            return [tok for tok in jieba.lcut(run) if tok.strip()]
    if len(run) == 1:
        return [run]
    return [run[i : i + 2] for i in range(len(run) - 1)]


def tokenize(text: str, *, use_jieba: bool | None = None) -> list[str]:
    """Split text into retrieval tokens.

    ``use_jieba=None`` (default) uses jieba when importable, else bigrams;
    ``True``/``False`` force the path (``True`` still falls back to bigrams
    when jieba is absent).
    """
    if use_jieba is None:
        use_jieba = _load_jieba() is not None
    tokens: list[str] = []
    tokens.extend(_WORD_RE.findall(text.lower()))
    for run in _CJK_RE.findall(text):
        tokens.extend(_cjk_tokens(run, use_jieba))
    return tokens


def est_tokens(text: str) -> int:
    """Rough LLM-token estimate: one per latin word, one per CJK character.

    Used only for budget trimming — stability matters more than accuracy.
    """
    words = len(_WORD_RE.findall(text.lower()))
    cjk_chars = sum(len(run) for run in _CJK_RE.findall(text))
    return words + cjk_chars
