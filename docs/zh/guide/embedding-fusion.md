# Embedding 融合

BM25 匹配词面。有时你要的是含义："海滨度假"应该召回写着"喜欢海边"的条目，
哪怕两者一个字都不重合。这就是可选的 `[embed]` extra 增加的东西 ——
**也只有**这个：

```bash
pip install "wikimem[embed]"   # 增加 httpx + numpy
```

```python
from wikimem import MemoryIndex, MemoryStore
from wikimem.vectors import HttpEmbedder

store = MemoryStore("memory/")
embedder = HttpEmbedder("https://api.example.com/v1", "bge-m3", api_key="sk-…")

index = MemoryIndex(store, embedder=embedder)
result = index.retrieve("海滨度假")   # 与"喜欢海边"零词面重合也能召回
print(result.embedding_used)          # False = 端点不可用，BM25 照常工作
```

不传 `embedder` → 整个模块根本不会被导入。零依赖内核保持完整。

## BM25 从不关闭

配置 embedder 后，**每次查询两路信号都跑**：

1. BM25 照常给所有条目打分。
2. query 被 embed，对向量索引做余弦打分。
3. 两组分数各自在候选并集上 **min-max 归一**，然后融合：
   `score = w · bm25 + (1 − w) · cos`，`w = fusion_weight`
   （默认 `0.5` —— 与 memU ADR-0007 收敛到的混合公式一致）。

BM25 抓词面、余弦抓含义，谁都不会被悄悄丢掉：只被一路信号找到的条目照样进入
候选集。关键词为主的场景把 `fusion_weight` 往 `1.0` 调，
改写/同义表达为主的场景往 `0.0` 调。

## 永远 fail-open

embedding 端点是网络依赖，wikimem 拒绝让它成为单点故障：

- 端点宕机、超时、密钥错误、响应异常 —— 余弦路径直接返回空，检索**静默降级为
  纯 BM25**，`result.embedding_used` 为 `False`。`retrieve` 绝不因端点不可用
  而抛错。
- 判定是逐 query 的。端点恢复后，下一个 query 自动恢复融合 ——
  没有需要复位的熔断器。

想知道融合路径实际跑了多少，在宿主日志里观察 `embedding_used`。

## 向量缓存

BM25 索引在启动时免费重建，向量不一样 —— 重算要花 embedding API 的钱。
所以向量放进一个**持久、增量更新的缓存**，就在 markdown 旁边，
并享有和其他派生状态相同的保证：

```
memory/
├── category/
│   ├── preferences.md
│   └── daily_life.md
├── journal.jsonl
├── vectors-000003.npy     ← float32 矩阵，一行一个条目
└── vectors.keys.jsonl     ← 明文：哪一行对应哪个条目（内容哈希）
```

- **按内容哈希建键。** 每次索引重建只 embed 新增或变化的条目（每批 64 条），
  未变的行直接复用、不发 API 请求。改个条目名，也只重新 embed 那一条。
- **该可读的地方是可读的。** `vectors.keys.jsonl` 是纯 JSONL —— 头一行指明
  当前 `.npy`，之后一行一条 `{category, name, hash}`。矩阵本身是数字，
  但*谁对应谁*永远是文本。
- **随时可删。** 两个文件删掉，下次 sync 自动重建。它永远不是事实源。
- **版本化的 `.npy`**（`vectors-000001.npy`、`-000002.npy`、……）：Windows
  不允许替换仍被活索引 memory-map 的文件，所以每次 sync 写新版本、
  尽力清理旧版本，清不掉的留给后续 sync。keys 与矩阵对不上的"撕裂"状态
  按"缓存不存在"处理并重建 —— 绝不信任损坏数据。

想把缓存放到别处（比如挪出同步盘），用
`MemoryIndex(store, embedder=..., vectors_dir="…")`。

## 内存故事：memmap 分层

全精度向量从不全量驻留内存：

- **第 0 层 —— 不超过 `binary_threshold` 条（默认 10 000）：** 对 float32
  **memmap** 做暴力余弦。哪些页驻留由操作系统页缓存决定；个人记忆规模下
  是微秒级。
- **第 1 层 —— 超过阈值：** 紧凑的 1-bit 签名（768 维下每条 96 字节）驻留
  内存做 Hamming 距离粗排；只有前 `k × 4` 个候选行从 memmap 读回，
  做精确余弦重排。

切换是自动的、按构建时条数判定；`binary_threshold` 是 `MemoryIndex`
的构造参数，精度/内存的取舍不同就调它。

## 自带 embedder —— 或自带索引

两个小 protocol 让整层可插拔（[参考](/zh/reference/vectors)）：

- **`Embedder`** —— 任何实现
  `embed(texts: list[str]) -> list[list[float]]` 的对象。`HttpEmbedder`
  覆盖一切 OpenAI 兼容的 `/embeddings` 端点（OpenAI、SiliconFlow、Ollama、
  vLLM、……）；包一个本地 sentence-transformers 也就五行。
- **`VectorIndex`** —— 检索端口：`search(query, top_k) -> [(row, score)]`。
  内置 `MemmapVectorIndex` 是默认后端；更重的后端（sqlite-vec、Qdrant
  local、……）适配到同一接口后面，检索代码一行不改。
  （接口借鉴 mem0 的 VectorStore 抽象 —— 借端口，不借默认后端。）
