# Wiki-links

wiki-link 是写在内容里的引用 —— 就是你在维基和 Obsidian 里见过的 `[[...]]`
语法 —— 在 wikimem 中它永远指向**一个条目（item）**：

```markdown
# preferences.md
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

# daily_life.md
## beach-trip-plan

计划夏天去海边旅行，看日出。
```

`[[daily_life:beach-trip-plan]]` 是一个两段式地址：**category**（哪个文件 ——
`daily_life.md`）+ **条目名**（文件里哪个 `##` 标题）。所以被链接的节点是
*条目*：一个有名字、自包含、几句话规模的记忆 —— **不是词，也不是整个文件**。

检索命中 `likes-the-sea` 时，会机械展开它的链接一跳，把整个
`beach-trip-plan` 条目一并注入 —— 不调 LLM、没有图数据库。
"图"就是文本本身，展开只是一次按名字的精确查找。

## 已经有搜索了，为什么还要链接？

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

## 链接是谁写的？

会打两对方括号的都行：

- **抽取 LLM**，在写入记忆的同一趟里。宿主把本轮检索刚浮现的条目名作为候选
  链接目标传给它，模型负责把新事实连到旧条目上 ——
  见[宿主集成](/zh/guide/host-integration)。
- **你自己**，在任何编辑器里。链接就是内容里的纯文本；下次 `rebuild()`
  （或进程重启）自然生效。

## 解析规则

链接解析刻意做得宽松，因为手改过的文件绝不能让读取崩溃：

- 语法是 `[[category:name]]` —— category 取到**第一个**冒号为止；
  两侧都不能含 `[`、`]`、换行或另一个冒号。
- 两侧的空白会被去掉；残缺或空的链接被解析器静默忽略（不是错误）。
- 条目名**从源头上**保持无冒号：`sanitize_item_name` 在写入时拒绝
  `[[`、`]]`、`:`、`|`、`#`，这让每条链接都无歧义、可 grep。

```python
from wikimem import parse_wiki_links

parse_wiki_links("… [[daily_life:beach-trip-plan]] 和 [[坏掉的链接 …")
# [WikiLink(category='daily_life', name='beach-trip-plan')]
```

## 悬空链接

文件是用户可编辑的，链接目标随时可能被改名或删除。wikimem 把这当作日常，
而不是数据损坏：

- 展开时跳过缺失的目标，继续处理其余链接。
- 未解析的地址记录在
  [`RetrievalResult.unresolved_links`](/zh/reference/api#retrievalresult)，
  宿主（或未来的 `wikimem graph` CLI）可以拿它提示修复。

## 边界：一跳，是刻意的

展开只做恰好一跳 —— 命中拉进它直接链接的目标，目标**不再**拉它自己的链接；
多跳链条会随着对话逐轮触达、逐跳浮现。一跳让注入的上下文与命中数成正比、
token 成本可预期、行为可解释（"这个条目在这里，因为那个命中链到了它"）。
token 预算的[前缀裁剪语义](/zh/guide/retrieval#_4-token-预算)出于同样的考虑。
