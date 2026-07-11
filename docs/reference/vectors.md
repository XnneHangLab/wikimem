# Vectors API

Everything on this page needs the `[embed]` extra (`httpx` + `numpy`) and
lives in `wikimem.vectors`:

```python
from wikimem.vectors import (
    Embedder, VectorIndex,          # protocols (the ports)
    HttpEmbedder,                   # OpenAI-compatible client
    VectorCache, MemmapVectorIndex, # default backends
    content_hash,
)
```

::: warning Import boundary
`wikimem.vectors` imports numpy at module level, so import it **only when
embedding is configured**. The top-level `wikimem` package never re-exports
it — the zero-dependency core stays intact, and `MemoryIndex` lazy-imports
this module only when you pass an `embedder`.
:::

Concepts and behavior (fusion formula, fail-open rules, tier story) are in
the [Embedding Fusion guide](/guide/embedding-fusion); this page is the API
contract.

## Protocols

### Embedder

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Anything that turns texts into equal-length float vectors. Exceptions are
treated as "endpoint down" by `MemoryIndex` — retrieval degrades to
BM25-only for that query instead of raising.

### VectorIndex

```python
class VectorIndex(Protocol):
    def search(self, query: Sequence[float], top_k: int) -> list[tuple[int, float]]: ...
```

The pluggable vector-search port (interface borrowed from mem0's VectorStore
abstraction — the port, not the backend). Rows are integer positions in the
caller's key order; scores are similarity, higher = better. Back it with
sqlite-vec, Qdrant local, or anything else without touching retrieval code.

## HttpEmbedder

```python
HttpEmbedder(
    base_url: str,            # e.g. "https://api.siliconflow.cn/v1"
    model: str,               # e.g. "BAAI/bge-m3"
    *,
    api_key: str | None = None,
    timeout: float = 10.0,
)
```

Client for any OpenAI-compatible `POST {base_url}/embeddings` endpoint.
httpx is imported and the connection opened lazily on first use; responses
are re-ordered by the API's `index` field, so batch order is preserved.
Raises on HTTP errors — which is exactly what the caller
(`MemoryIndex._cosine_scores`) catches to implement fail-open.

## VectorCache

```python
VectorCache(root: Path | str)
```

Persistent, incrementally-updated vector cache on disk. Layout (also
described in [On-disk Format](/reference/file-format#vector-cache-embed-extra)):

- `vectors.keys.jsonl` — plain text: a header line
  `{"vectors_file": "vectors-000003.npy"}`, then one
  `{"category", "name", "hash"}` line per matrix row.
- `vectors-NNNNNN.npy` — float32 matrix, one row per key line, loaded
  `mmap_mode="r"`.

### `load() -> tuple[list[dict], np.ndarray | None]`

Returns `(keys, matrix)` or `([], None)` when absent. **Torn state** (missing
`.npy`, or key count ≠ row count) is treated as absent — the next `sync`
rebuilds; corruption is never trusted or propagated.

### `sync(entries, embedder, *, batch_size=64)`

```python
entries: list[tuple[tuple[str, str], str]]   # ((category, name), text)
```

Brings the cache in line with `entries`, in order:

- Rows whose `sha256(text)` content hash is unchanged are **reused without an
  API call**; new/changed texts are embedded in batches of `batch_size`.
- When nothing changed, returns the existing cache without writing.
- Otherwise writes a **new versioned** `.npy` (atomic temp + replace), updates
  the keys file, then sweeps old versions best-effort. Versioning exists
  because Windows forbids replacing a file that a live index still
  memory-maps; stale versions are swept by later syncs.
- Empty `entries` clears the cache files.

`content_hash(text: str) -> str` — the sha256 hex digest used for the above.

## MemmapVectorIndex

```python
MemmapVectorIndex(matrix: np.ndarray, *, binary_threshold: int = 10_000)
```

Default `VectorIndex` backend over a float32 (mem)mapped matrix. Two tiers,
chosen at construction by `len(matrix)`:

- **Tier 0** (`≤ binary_threshold` rows): brute-force cosine over the memmap.
  Full-precision vectors are never all RAM-resident; the OS page cache
  decides what stays hot.
- **Tier 1** (above): 1-bit signatures (`packbits(matrix > 0)`, 96 bytes per
  item at 768 dims) held in RAM; a query is coarse-ranked by Hamming
  distance, the top `top_k × 4` candidates are read from the memmap, and
  exact cosine reranks just those. (When `top_k × 4` would cover most of the
  matrix anyway, it falls back to exact scoring.)

`search(query, top_k)` returns `[(row, score), …]` sorted by cosine
similarity, descending. Zero-norm rows are guarded (no division by zero);
`len(index)` reports the row count.
