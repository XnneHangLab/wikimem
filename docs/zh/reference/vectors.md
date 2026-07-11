# 向量 API

本页的一切都需要 `[embed]` extra（`httpx` + `numpy`），住在
`wikimem.vectors`：

```python
from wikimem.vectors import (
    Embedder, VectorIndex,          # protocols（端口）
    HttpEmbedder,                   # OpenAI 兼容客户端
    VectorCache, MemmapVectorIndex, # 默认后端
    content_hash,
)
```

::: warning 导入边界
`wikimem.vectors` 在模块级导入 numpy，所以**只在确实配置了 embedding 时**
才导入它。顶层 `wikimem` 包从不重导出它 —— 零依赖内核保持完整；
`MemoryIndex` 只在你传入 `embedder` 时才惰性导入本模块。
:::

概念与行为（融合公式、fail-open 规则、分层故事）在
[Embedding 融合指南](/zh/guide/embedding-fusion)；本页只讲 API 契约。

## Protocols

### Embedder

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

任何能把文本变成等长浮点向量的对象。抛出的异常被 `MemoryIndex` 视为
"端点不可用" —— 该次查询降级为纯 BM25，而不是向上抛。

### VectorIndex

```python
class VectorIndex(Protocol):
    def search(self, query: Sequence[float], top_k: int) -> list[tuple[int, float]]: ...
```

可插拔的向量检索端口（接口借鉴 mem0 的 VectorStore 抽象 ——
借端口，不借后端）。row 是调用方 key 顺序中的整数位置；score 是相似度，
越大越好。想换 sqlite-vec、Qdrant local 或别的后端，适配到这个接口即可，
检索代码一行不改。

## HttpEmbedder

```python
HttpEmbedder(
    base_url: str,            # 如 "https://api.siliconflow.cn/v1"
    model: str,               # 如 "BAAI/bge-m3"
    *,
    api_key: str | None = None,
    timeout: float = 10.0,
)
```

任何 OpenAI 兼容 `POST {base_url}/embeddings` 端点的客户端。httpx 的导入与
连接都在首次使用时才发生；响应按 API 返回的 `index` 字段重排，
批次顺序不会乱。HTTP 错误会抛出 —— 而这正是调用方
（`MemoryIndex._cosine_scores`）用来实现 fail-open 的捕获点。

## VectorCache

```python
VectorCache(root: Path | str)
```

磁盘上的持久、增量更新向量缓存。布局（也见
[磁盘格式](/zh/reference/file-format#向量缓存-embed-extra)）：

- `vectors.keys.jsonl` —— 明文：头一行
  `{"vectors_file": "vectors-000003.npy"}`，之后矩阵每行对应一条
  `{"category", "name", "hash"}`。
- `vectors-NNNNNN.npy` —— float32 矩阵，与 key 行一一对应，
  以 `mmap_mode="r"` 加载。

### `load() -> tuple[list[dict], np.ndarray | None]`

返回 `(keys, matrix)`，缓存不存在时返回 `([], None)`。**撕裂状态**
（`.npy` 缺失，或 key 数与行数不符）按"不存在"处理 —— 下次 `sync` 重建；
损坏数据从不被信任、从不向外传播。

### `sync(entries, embedder, *, batch_size=64)`

```python
entries: list[tuple[tuple[str, str], str]]   # ((category, name), text)
```

把缓存对齐到 `entries`（保持顺序）：

- `sha256(text)` 内容哈希未变的行**直接复用、不发 API 请求**；
  新增/变化的文本按 `batch_size` 分批 embed。
- 什么都没变时，直接返回现有缓存、不写盘。
- 否则写一个**新版本号**的 `.npy`（临时文件 + 原子替换），更新 keys 文件，
  再尽力清扫旧版本。版本化的原因：Windows 不允许替换仍被活索引 memory-map
  的文件；清不掉的旧版本由后续 sync 收拾。
- `entries` 为空时清空缓存文件。

`content_hash(text: str) -> str` —— 上述所用的 sha256 十六进制摘要。

## MemmapVectorIndex

```python
MemmapVectorIndex(matrix: np.ndarray, *, binary_threshold: int = 10_000)
```

架在 float32（mem）map 矩阵上的默认 `VectorIndex` 后端。按构造时的
`len(matrix)` 选择两层之一：

- **第 0 层**（`≤ binary_threshold` 行）：对 memmap 暴力余弦。全精度向量
  从不全量驻留内存，页缓存冷热由操作系统决定。
- **第 1 层**（超过阈值）：1-bit 签名（`packbits(matrix > 0)`，768 维下
  每条 96 字节）驻留内存；query 先按 Hamming 距离粗排，取前 `top_k × 4`
  个候选行从 memmap 读回，仅对它们做精确余弦重排。
  （当 `top_k × 4` 已覆盖大半个矩阵时，退回全量精确打分。）

`search(query, top_k)` 返回按余弦相似度降序的 `[(row, score), …]`。
零范数行有保护（不会除零）；`len(index)` 报告行数。
