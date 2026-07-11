# wikimem

[English](README.md) | 简体中文 | [文档](https://wikimem.xnnehang.top/zh/)

<!-- 与 README.md 保持同步：任一文件更新时请同步另一份 -->

面向 AI Agent 的文件优先记忆系统：**纯 markdown 之上的 categories + wiki-links**。
不需要数据库、不需要 embedding 模型、不需要 docker —— `pip install wikimem` 即可使用。

## 安装

```bash
pip install wikimem        # 默认安装 —— 开箱即用，功能完整
pip install "wikimem[all]" # 不想纠结就装这个，可选增强全都带上
```

**没有"模式"这回事。** wikimem 只有一条管线。extras 只是解锁可选增强：
装了就自动生效、彼此之间不冲突 —— 全装上也不会改变任何行为，直到你真正用到它。

| 安装方式 | 增加什么 | 使用场景 |
|---|---|---|
| `wikimem` | 无 —— 零依赖 | 功能完整：存储、BM25 检索（中文用字符 bigram）、wiki-links、journal |
| `wikimem[zh]` | jieba | 中文关键词召回比 bigram 更准 —— 装上即自动启用，无需任何配置 |
| `wikimem[embed]` | httpx + numpy | 语义召回（按含义而不是词面匹配）—— 只有传入 `embedder` 才会启用；端点挂了自动回退 BM25 |
| `wikimem[all]` | 以上全部 | "别让我做选择"选项 |

## 设计规则

1. **markdown 文件是唯一事实源。** 每个分类一个文件（`memory/preferences.md`），
   每个 `##` 标题一个条目。可以直接阅读、编辑、diff —— 你的编辑器就是管理界面。
2. **磁盘上没有不可读的真相。** 一切派生产物（索引、向量缓存）都可删除、可从文件
   重建。BM25 索引在启动时于内存中构建。
3. **永不阻塞对话。** 检索是同步的、有 token 预算的、fail-open 的（0 次 LLM 调用）；
   记忆写入由宿主异步执行（至多 1 次 LLM 调用）。
4. **"发生了什么"永远可以回答。** 每次变更向 `journal.jsonl` 追加一行；
   检索可以解释自己的打分。

## 什么是 wiki-link，为什么用它

wiki-link 是写在内容里的引用 —— 就是你在维基和 Obsidian 里见过的 `[[...]]`
语法 —— 在 wikimem 中它永远指向**一个条目（item）**：

```markdown
# preferences.md
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->

# daily_life.md
## beach-trip-plan

计划夏天去海边旅行，看日出。
```

`[[daily_life:beach-trip-plan]]` 是一个两段式地址：**category**（哪个文件 ——
`daily_life.md`）+ **条目名**（文件里哪个 `##` 标题）。所以被链接的节点是
*条目*：一个有名字、自包含、几句话规模的记忆 —— **不是词，也不是整个文件**。
检索命中 `likes-the-sea` 时，会机械展开它的链接一跳，把整个
`beach-trip-plan` 条目一并注入 —— 不调 LLM、没有图数据库；"图"就是文本本身，
展开只是一次按名字的精确查找。

已经有搜索了，为什么还要链接？

- **搜索找到的是"词面相似"，链接记录的是"含义相关"。** 咖啡偏好和早晨习惯
  可能一个词都不重合 —— 关键词（往往连 embedding）都搭不上，但记忆写入时
  留下的一条链接可以。
- **全程同一个单元。** 链接目标就是检索排序、token 预算裁剪所用的同一个单元：
  条目。比 Obsidian 的"文件级节点"更细 —— 展开一条链接永远不会把整份文档
  灌进 prompt。
- **人和 LLM 都能读写。** 抽取 LLM 在写入记忆的同一趟里顺手产出链接；
  你可以在任何编辑器里增删改它；`git diff` 看得见。
- **零基础设施、坏了不炸。** 它取代的是图数据库（前代设计为此跑着 Neo4j）。
  悬空链接 —— 目标被改名或删除 —— 会被容忍并报告，绝不崩溃。

## 状态

Pre-alpha，按里程碑逐步构建
（设计文档：XnneHangLab ADR-0001 —— 记忆管线）：

- M1 ✅ —— 存储层：分类文件、条目模型 + 元数据、
  wiki-link 解析、`journal.jsonl`、原子写入
- M2 ✅ —— 检索：内存 BM25（字符 bigram 兜底，`[zh]` extra 提供
  jieba 分词）、一跳 wiki-link 展开、token 预算、explain
- **M3（当前）** —— 可选 embedding 融合（`[embed]` extra）：内容哈希向量缓存
  （版本化 `.npy` + 明文 keys）、memmap 分层（1 万条以上二值量化）、可插拔
  `VectorIndex` 端口、端点不可用时静默回退纯 BM25
- M4 —— CLI：`ls / show / grep / explain / graph`

## 快速上手

```python
from wikimem import MemoryIndex, MemoryStore

store = MemoryStore("memory/")
store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")
store.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")

index = MemoryIndex(store)  # 内存 BM25，store 写入后自动重建
result = index.retrieve("想去海边玩", budget_tokens=800)
for entry in result.items:
    # 命中条目按分数排序；每个命中后面跟着它一跳展开的 wiki-link 目标
    print(entry.source, entry.item.name, entry.score, entry.matched_terms)
```

检索 0 次 LLM 调用，BM25 索引永不落盘 —— 没有可丢的东西。安装 `wikimem[zh]`
获得 jieba 中文分词（默认为字符 bigram）。

可选语义融合（`pip install wikimem[embed]`）—— **BM25 从不关闭**：配置
embedder 后每次查询两路信号都跑、各自 min-max 归一后融合（与 memU ADR-0007
收敛到的混合公式一致）。BM25 抓词面、余弦抓含义：

```python
from wikimem.vectors import HttpEmbedder

embedder = HttpEmbedder("https://api.example.com/v1", "bge-m3", api_key="sk-…")
index = MemoryIndex(store, embedder=embedder)
result = index.retrieve("海滨度假")   # 与"喜欢海边"零词面重合也能召回
print(result.embedding_used)          # False = 端点不可用，BM25 照常工作
```

向量存在 markdown 旁边的内容哈希缓存里（版本化 `vectors-*.npy` + 可读的
`vectors.keys.jsonl`）—— 增量更新、随时可删、永远不是事实源。embedding
端点不可达时检索静默降级为纯 BM25，绝不抛错。

## 参与开发

```bash
uv sync
uv run pytest
```

Apache-2.0。抽取 prompt 的设计借鉴自
[memU](https://github.com/NevaMind-AI/memU)（Apache-2.0）—— 见 lab ADR-0002。
