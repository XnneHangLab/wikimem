# 检索

```python
result = index.retrieve(
    "想去海边玩",
    limit=10,           # 搜索命中的上限（链接展开之前）
    budget_tokens=800,  # 注入内容的 token 上限，None = 不设限
    expand_links=True,  # 一跳 wiki-link 展开
    explain=False,      # True → 保留被预算裁掉的部分，便于检查
)
```

`retrieve` 是**同步的**、**0 次 LLM 调用**，并且对可选路径的降级永不抛错 ——
它就是为直接坐在 Agent 热路径上而设计的，宿主在外面再包一层 fail-open。
本页按执行顺序过一遍这条管线。

## 1. 分词

query 和文档过同一个零依赖分词器：

- ASCII/拉丁串 → 小写单词（`[a-z0-9]+`）。
- 中日韩文本 → **字符 bigram**（"海边玩" → `海边`、`边玩`）——
  不装分词器也有可用的关键词召回。
- 装了 `[zh]` extra 后，CJK 走 **jieba**。检测是自动的；
  `MemoryIndex(store, use_jieba=...)` 可以强制路径（`True` 在 jieba 缺席时
  仍回退 bigram，`False` 永不使用 —— 适合可复现的基准测试）。

## 2. BM25 排序

每个条目按经典 BM25（`k1 = 1.5`，`b = 0.75`）对 query 打分，索引内容是条目的
**名字 + 内容**。这个索引：

- **只存在于内存** —— 永不落盘；个人记忆规模（几 MB 文本）下重建近乎免费。
- **惰性保鲜** —— `MemoryStore` 每次写入递增 revision 计数器，`retrieve`
  发现过期就重建。进程外的文件修改（编辑器、`git pull`）计数器看不见 ——
  那之后调用 `index.rebuild()`，或依赖进程启动时的重建。

得分最高的 `limit` 个条目成为**命中（hit）**。如果配置了
[embedder](/zh/guide/embedding-fusion)，余弦分数在这一步与 BM25 融合 ——
BM25 本身从不关闭。

## 3. 一跳链接展开

`expand_links=True`（默认）时，每个命中的 wiki-links 按 `(category, name)`
精确查找解析，目标条目**紧跟在所属命中之后**注入，标记 `source="link"`：

```text
hit   likes-the-sea      score=3.87   matched_terms=['海边', ...]
link  beach-trip-plan    via='likes-the-sea'
hit   三亚之行            score=2.41   ...
```

- 展开是**一跳**、纯机械的 —— 不打分、不调 LLM、不递归
  （[为什么](/zh/guide/wiki-links#边界-一跳-是刻意的)）。
- 整个序列全局去重：已经在场的条目（无论作为命中还是更早的链接目标）
  不会注入第二次。
- 目标不存在的链接被跳过，并记录在 `result.unresolved_links`。

## 4. Token 预算

序列按 `budget_tokens` 做**前缀裁剪**：按注入顺序保留，直到下一个条目会超出
预算为止。两条性质值得记住：

- **第一个条目永远保留**，哪怕它单独就超预算 —— 检索绝不因为最佳命中太长
  而返回空。
- 成本用 `est_tokens` 估算，一个刻意粗糙的估计（拉丁词算一个、CJK 字符算
  一个）。它的职责是**稳定的裁剪**，不是精确 —— 别拿去算 API 账单。

`result.budget_used` 报告幸存内容的估算总量。

## 5. 读结果

```python
result = index.retrieve("咖啡", budget_tokens=800, explain=True)

result.items             # list[RetrievedItem] —— 预算内幸存者，注入顺序
result.budget_used       # 上面这些的估算 token 总量
result.embedding_used    # True 仅当余弦路径真的跑了
result.unresolved_links  # ['[[daily_life:renamed-item]]', ...]
result.dropped           # 被预算裁掉的（仅 explain=True）
```

每个 `RetrievedItem` 自带证据：

| 字段 | 含义 |
|---|---|
| `source` | `"hit"`（搜索命中）或 `"link"`（一跳展开） |
| `score` | 排序分 —— 跑了 embedding 就是融合分，否则是 BM25 |
| `bm25_score` / `cos_score` | `score` 背后的两路原始信号（仅命中） |
| `via` | 链接条目：把它拉进来的那个命中 |
| `matched_terms` | 该条目里出现的 query 词 —— 命中的"为什么" |
| `tokens_est` | 该条目占用的预算 |

这就是设计规则 4 的落地：宿主可以记录、展示、调试每条记忆进入 prompt 的确切
原因。

## 值得知道的边界情况

- **query 分不出词**（比如纯标点）→ 返回空结果；除非 embedding 路径在跑 ——
  余弦仍可能排出 BM25 排不了的东西。
- **对已有名字 `add` 即更新** —— 索引在下次 `retrieve` 时通过 revision
  计数器感知。
- **分数只在语料内可比。** BM25 依赖文档频率，融合分又按 query 做 min-max
  归一 —— 只在同一次结果内比较，不要跨 query、跨 store 比。
