"""Optional embedding layer (the ``[embed]`` extra: httpx + numpy).

Everything here is **derived state** (ADR hard constraint 3) with one nuance:
unlike the BM25 index (rebuilt free at startup), vectors cost embedding-API
money to recompute — so the vector cache is a *persistent* cache, keyed by
content hash and updated incrementally. Deleting it is always safe; it
rebuilds on the next sync.

On-disk layout: ``vectors.keys.jsonl`` starts with a header line
``{"vectors_file": "vectors-<n>.npy"}`` followed by one
``{"category","name","hash"}`` line per matrix row. Each sync writes a NEW
versioned ``.npy`` instead of replacing the current one — Windows forbids
replacing/deleting a file that is still memory-mapped by a live index, so
old versions are removed best-effort and swept on later syncs.

Full-precision vectors are never all RAM-resident: ≤ ``binary_threshold``
items use brute-force cosine over a float32 memmap (the OS page cache decides
what is hot); above it, 1-bit signatures (96 B/item @768d) live in RAM for
Hamming coarse ranking, and only the top candidates are read back from the
memmap for exact rerank.

Import note: this module imports numpy at module level — it must only be
imported when embedding is actually configured (``wikimem/__init__`` does NOT
re-export it, keeping the zero-dependency core intact).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

_KEYS_FILENAME = "vectors.keys.jsonl"
_DATA_RE = re.compile(r"^vectors-(\d+)\.npy$")

# Popcount lookup table for Hamming distance over packed bits (numpy<2 compat).
_POPCOUNT = np.array([i.bit_count() for i in range(256)], dtype=np.uint16)


class Embedder(Protocol):
    """Anything that turns texts into equal-length float vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorIndex(Protocol):
    """The pluggable vector-search port (lab ADR-0001, borrowed from mem0's
    VectorStore abstraction — adopt the interface, not the default backend).

    Contract: rows are integer positions into the caller's key order; heavier
    backends (sqlite-vec, Qdrant local, ...) adapt behind this same surface.
    """

    def search(self, query: Sequence[float], top_k: int) -> list[tuple[int, float]]: ...


class HttpEmbedder:
    """OpenAI-compatible ``POST {base_url}/embeddings`` client (httpx, lazy)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx  # Lazy-import: [embed] extra

            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(headers=headers, timeout=self.timeout)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._get_client().post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [entry["embedding"] for entry in sorted(data, key=lambda e: e["index"])]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VectorCache:
    """Persistent, incrementally-updated vector cache on disk.

    ``vectors.keys.jsonl`` (plain text — readability lives here) maps rows to
    ``(category, name, content-hash)`` and names the current ``.npy`` file.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.keys_path = self.root / _KEYS_FILENAME

    # ------------------------------------------------------------------ read

    def load(self) -> tuple[list[dict], np.ndarray | None]:
        if not self.keys_path.exists():
            return [], None
        lines = [
            line for line in self.keys_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        if not lines:
            return [], None
        header = json.loads(lines[0])
        data_name = header.get("vectors_file")
        data_path = self.root / data_name if data_name else None
        if data_path is None or not data_path.exists():
            return [], None
        keys = [json.loads(line) for line in lines[1:]]
        matrix = np.load(data_path, mmap_mode="r")
        if len(keys) != len(matrix):  # torn state — treat as absent, resync rebuilds
            return [], None
        return keys, matrix

    # ----------------------------------------------------------------- write

    def sync(
        self,
        entries: list[tuple[tuple[str, str], str]],
        embedder: Embedder,
        *,
        batch_size: int = 64,
    ) -> tuple[list[dict], np.ndarray | None]:
        """Bring the cache in line with ``entries`` ((category, name), text).

        Rows whose content hash is unchanged are reused without an API call;
        new/changed texts are embedded in batches. Returns keys + a read-only
        memmap in entry order. When nothing changed, returns the existing
        cache without writing.
        """
        old_keys, old_matrix = self.load()
        keys = [
            {"category": category, "name": name, "hash": content_hash(text)}
            for (category, name), text in entries
        ]
        if keys == old_keys and old_matrix is not None:
            return old_keys, old_matrix

        old_rows = {(k["category"], k["name"], k["hash"]): i for i, k in enumerate(old_keys)}
        rows: list[np.ndarray | None] = []
        pending_texts: list[str] = []
        pending_slots: list[int] = []
        for key, ((_, _), text) in zip(keys, entries):
            reuse = old_rows.get((key["category"], key["name"], key["hash"]))
            if reuse is not None and old_matrix is not None:
                rows.append(np.array(old_matrix[reuse], dtype=np.float32, copy=True))
            else:
                rows.append(None)
                pending_texts.append(text)
                pending_slots.append(len(rows) - 1)
        self._close(old_matrix)

        for start in range(0, len(pending_texts), batch_size):
            batch = pending_texts[start : start + batch_size]
            vectors = embedder.embed(batch)
            for offset, vector in enumerate(vectors):
                rows[pending_slots[start + offset]] = np.asarray(vector, dtype=np.float32)

        if not rows:
            try:
                self.keys_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._sweep(keep=None)
            return [], None

        matrix = np.stack([row for row in rows if row is not None])
        data_name = self._next_data_name()
        self._write_atomic(data_name, keys, matrix)
        self._sweep(keep=data_name)
        return self.load()

    # ------------------------------------------------------------- internals

    def _next_data_name(self) -> str:
        highest = 0
        for path in self.root.glob("vectors-*.npy"):
            match = _DATA_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"vectors-{highest + 1:06d}.npy"

    def _write_atomic(self, data_name: str, keys: list[dict], matrix: np.ndarray) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp_vec = tempfile.mkstemp(dir=self.root, suffix=".npy")
        os.close(fd)
        np.save(tmp_vec, matrix)  # mkstemp name already ends with .npy — no rename surprise
        os.replace(tmp_vec, self.root / data_name)
        fd, tmp_keys = tempfile.mkstemp(dir=self.root, suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"vectors_file": data_name}) + "\n")
            for key in keys:
                f.write(json.dumps(key, ensure_ascii=False) + "\n")
        os.replace(tmp_keys, self.keys_path)

    def _sweep(self, keep: str | None) -> None:
        """Best-effort removal of stale versioned files (a live memmap on
        Windows blocks deletion — those get swept by a later sync)."""
        for path in self.root.glob("vectors-*.npy"):
            if keep is not None and path.name == keep:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    @staticmethod
    def _close(matrix: np.ndarray | None) -> None:
        mm = getattr(matrix, "_mmap", None)
        if mm is not None:
            try:
                mm.close()
            except (BufferError, OSError):
                pass


class MemmapVectorIndex:
    """Default :class:`VectorIndex` backend over a float32 (mem)mapped matrix.

    Tier 0 (≤ ``binary_threshold`` rows): brute-force cosine.
    Tier 1: RAM-resident 1-bit signatures → Hamming top-``k×4`` candidates →
    exact cosine rerank on just those memmap rows.
    """

    def __init__(self, matrix: np.ndarray, *, binary_threshold: int = 10_000) -> None:
        self._matrix = matrix
        norms = np.linalg.norm(np.asarray(matrix, dtype=np.float32), axis=1)
        self._norms = np.where(norms == 0.0, 1.0, norms)
        self._binary = len(matrix) > binary_threshold
        self._signatures = np.packbits(np.asarray(matrix) > 0, axis=1) if self._binary else None

    def __len__(self) -> int:
        return len(self._matrix)

    def _cosine(self, row_ids: np.ndarray, query: np.ndarray, query_norm: float) -> np.ndarray:
        rows = np.asarray(self._matrix[row_ids], dtype=np.float32)
        return (rows @ query) / (self._norms[row_ids] * query_norm)

    def search(self, query: Sequence[float], top_k: int) -> list[tuple[int, float]]:
        if len(self._matrix) == 0 or top_k <= 0:
            return []
        q = np.asarray(query, dtype=np.float32)
        q_norm = float(np.linalg.norm(q)) or 1.0
        top_k = min(top_k, len(self._matrix))

        if self._signatures is not None and top_k * 4 < len(self._matrix):
            q_sig = np.packbits(q > 0)
            hamming = _POPCOUNT[np.bitwise_xor(self._signatures, q_sig)].sum(axis=1)
            candidate_count = top_k * 4
            candidates = np.argpartition(hamming, candidate_count)[:candidate_count]
        else:
            candidates = np.arange(len(self._matrix))

        scores = self._cosine(candidates, q, q_norm)
        order = np.argsort(scores)[::-1][:top_k]
        return [(int(candidates[i]), float(scores[i])) for i in order]
