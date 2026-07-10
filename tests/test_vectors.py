"""M3: embedding fusion, vector cache, memmap tiers, VectorIndex port."""

import numpy as np
import pytest

from wikimem import MemoryIndex, MemoryStore
from wikimem.vectors import HttpEmbedder, MemmapVectorIndex, VectorCache


class StubEmbedder:
    """Deterministic 4-dim semantic space: [sea, coffee, code, other].

    Maps texts by keyword so tests can assert *semantic* recall where BM25
    has zero lexical overlap.
    """

    def __init__(self):
        self.calls = 0
        self.texts_embedded = 0

    def _vec(self, text: str) -> list[float]:
        sea = any(w in text for w in ("海", "ocean", "beach", "度假", "日出"))
        coffee = any(w in text for w in ("咖啡", "coffee", "手冲"))
        code = any(w in text for w in ("python", "代码", "开发"))
        v = [1.0 if sea else 0.0, 1.0 if coffee else 0.0, 1.0 if code else 0.0, 0.1]
        return v

    def embed(self, texts):
        self.calls += 1
        self.texts_embedded += len(texts)
        return [self._vec(t) for t in texts]


class BoomEmbedder:
    def embed(self, texts):
        raise ConnectionError("endpoint down")


@pytest.fixture()
def store(tmp_path):
    s = MemoryStore(tmp_path / "memory")
    s.add("preferences", "likes-the-sea", "喜欢海边，提到过想去海边玩。")
    s.add("preferences", "coffee", "只喝手冲咖啡，不加糖。")
    s.add("career", "backend-dev", "从市场营销转行做了后端开发，写 Python。")
    return s


def test_semantic_recall_beyond_bm25(store):
    # Query "海滨度假" shares no bigram with "喜欢海边…" (海滨/滨度/度假 vs 喜欢/欢海/海边)
    # -> BM25 alone misses; the stub embedder maps both to the sea axis.
    bm25_only = MemoryIndex(store, use_jieba=False)
    assert all(r.item.name != "likes-the-sea" for r in bm25_only.retrieve("海滨度假").items)

    fused = MemoryIndex(store, use_jieba=False, embedder=StubEmbedder())
    result = fused.retrieve("海滨度假")
    assert result.embedding_used is True
    names = [r.item.name for r in result.items]
    assert "likes-the-sea" in names
    top = result.items[0]
    assert top.cos_score and top.cos_score > 0


def test_fusion_keeps_bm25_signal(store):
    fused = MemoryIndex(store, use_jieba=False, embedder=StubEmbedder())
    result = fused.retrieve("手冲咖啡")
    assert result.items[0].item.name == "coffee"
    assert result.items[0].bm25_score and result.items[0].bm25_score > 0


def test_degrades_to_bm25_when_embedder_fails(store, tmp_path):
    # Build the cache with a working embedder first, then swap in a broken one.
    working = MemoryIndex(store, use_jieba=False, embedder=StubEmbedder())
    working.retrieve("咖啡")  # builds cache + index
    broken = MemoryIndex(store, use_jieba=False, embedder=BoomEmbedder())
    result = broken.retrieve("手冲咖啡")
    assert result.embedding_used is False
    assert result.items and result.items[0].item.name == "coffee"  # BM25 path alive


def test_cache_is_incremental(store, tmp_path):
    embedder = StubEmbedder()
    index = MemoryIndex(store, use_jieba=False, embedder=embedder)
    index.retrieve("咖啡")
    assert embedder.texts_embedded == 4  # 3 items + 1 query

    # Unchanged store, fresh index over the same cache dir: only the query embeds.
    embedder2 = StubEmbedder()
    index2 = MemoryIndex(store, use_jieba=False, embedder=embedder2)
    index2.retrieve("咖啡")
    assert embedder2.texts_embedded == 1

    # One item changes -> exactly one re-embedding (+ the query).
    store.add("preferences", "coffee", "戒了咖啡，改喝茶。")
    embedder3 = StubEmbedder()
    index3 = MemoryIndex(store, use_jieba=False, embedder=embedder3)
    index3.retrieve("茶")
    assert embedder3.texts_embedded == 2


def test_cache_files_are_deletable(store, tmp_path):
    import gc

    embedder = StubEmbedder()
    index = MemoryIndex(store, use_jieba=False, embedder=embedder)
    index.retrieve("咖啡")
    root = tmp_path / "memory"
    data_files = list(root.glob("vectors-*.npy"))
    assert len(data_files) == 1 and (root / "vectors.keys.jsonl").exists()

    # Release the live memmap first — Windows blocks deleting a mapped file.
    del index
    gc.collect()
    data_files[0].unlink()
    (root / "vectors.keys.jsonl").unlink()

    fresh = StubEmbedder()
    index2 = MemoryIndex(store, use_jieba=False, embedder=fresh)
    assert index2.retrieve("咖啡").embedding_used is True  # rebuilt from scratch
    assert fresh.texts_embedded == 4  # 3 items + 1 query


def test_vector_files_are_not_categories(store):
    MemoryIndex(store, use_jieba=False, embedder=StubEmbedder()).retrieve("咖啡")
    assert set(store.categories()) == {"preferences", "career"}


def test_binary_tier_matches_bruteforce_top1():
    rng = np.random.default_rng(7)
    matrix = rng.normal(size=(64, 32)).astype(np.float32)
    query = matrix[13] + rng.normal(scale=0.01, size=32).astype(np.float32)

    brute = MemmapVectorIndex(matrix, binary_threshold=10_000)  # tier 0
    binary = MemmapVectorIndex(matrix, binary_threshold=8)  # force tier 1
    assert binary._signatures is not None
    assert brute.search(query, 1)[0][0] == 13
    assert binary.search(query, 1)[0][0] == 13


def test_vector_index_port_shape():
    matrix = np.eye(4, dtype=np.float32)
    index = MemmapVectorIndex(matrix)
    hits = index.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert hits[0] == (0, pytest.approx(1.0))
    assert len(hits) == 2 and all(isinstance(r, int) for r, _ in hits)


def test_http_embedder_openai_shape():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        assert request.headers["authorization"] == "Bearer sk-test"
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "bge-m3"
        # Respond out of order to prove index-based reordering.
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    embedder = HttpEmbedder("http://fake/v1", "bge-m3", api_key="sk-test")
    embedder._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer sk-test"},
    )
    vectors = embedder.embed(["a", "b"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_cache_sync_roundtrip(tmp_path):
    cache = VectorCache(tmp_path)
    embedder = StubEmbedder()
    entries = [(("c", "one"), "咖啡"), (("c", "two"), "海边")]
    keys, matrix = cache.sync(entries, embedder)
    assert [k["name"] for k in keys] == ["one", "two"]
    assert matrix.shape == (2, 4)
    # Removing an entry shrinks the cache on next sync.
    keys2, matrix2 = cache.sync(entries[:1], embedder)
    assert len(keys2) == 1 and matrix2.shape[0] == 1
