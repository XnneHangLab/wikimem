# wikimem

[English](README.md) | 简体中文

<!-- 与 README.md 保持同步：任一文件更新时请同步另一份 -->

面向 AI Agent 的文件优先记忆系统：**纯 markdown 之上的 categories + wiki-links**。
不需要数据库、不需要 embedding 模型、不需要 docker —— `pip install wikimem` 即可使用。

## 设计规则

1. **markdown 文件是唯一事实源。** 每个分类一个文件（`memory/preferences.md`），
   每个 `##` 标题一个条目。可以直接阅读、编辑、diff —— 你的编辑器就是管理界面。
2. **磁盘上没有不可读的真相。** 一切派生产物（索引、向量缓存）都可删除、可从文件
   重建。BM25 索引在启动时于内存中构建。
3. **永不阻塞对话。** 检索是同步的、有 token 预算的、fail-open 的（0 次 LLM 调用）；
   记忆写入由宿主异步执行（至多 1 次 LLM 调用）。
4. **"发生了什么"永远可以回答。** 每次变更向 `journal.jsonl` 追加一行；
   检索可以解释自己的打分。

跨分类关联使用内容内 wiki-links：

```markdown
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->
```

检索命中条目后，机械展开其链接一跳 —— 不走 LLM，不需要图数据库。

## 状态

Pre-alpha，按里程碑逐步构建
（设计文档：XnneHangLab ADR-0001 —— 记忆管线）：

- **M1（当前）** —— 存储层：分类文件、条目模型 + 元数据、
  wiki-link 解析、`journal.jsonl`、原子写入
- M2 —— 检索：内存 BM25（字符 n-gram 兜底，`[zh]` extra 提供 jieba 分词）、
  wiki-link 展开、token 预算、`explain`
- M3 —— 可选 embedding 融合（`[embed]` extra）：memmap 向量、
  1 万条以上二值量化、可插拔 `VectorIndex` 端口
- M4 —— CLI：`ls / show / grep / explain / graph`

## 快速上手（M1 接口）

```python
from wikimem import MemoryStore

store = MemoryStore("memory/")
store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")

item = store.get("preferences", "likes-the-sea")
print(item.links)          # [WikiLink(category='daily_life', name='beach-trip-plan')]
print(store.categories())  # ['preferences']
```

## 参与开发

```bash
uv sync
uv run pytest
```

Apache-2.0。抽取 prompt 的设计借鉴自
[memU](https://github.com/NevaMind-AI/memU)（Apache-2.0）—— 见 lab ADR-0002。
