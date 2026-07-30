# ADR-0006: RecallFile / RecallItem — 读侧统一，写侧分立

- **状态**：Accepted（2026-07-28 提出，随设计 PR [#28](https://github.com/XnneHangLab/wikimem/pull/28) 评审定稿）
- **日期**：2026-07-28
- **实施**：⚠️ 部分落地（编号对应文末「实施」四条）—— ① 改名清扫 [#29](https://github.com/XnneHangLab/wikimem/pull/29)（代码）+ [#30](https://github.com/XnneHangLab/wikimem/pull/30)（文档）、② 形式化 RecallFile [#32](https://github.com/XnneHangLab/wikimem/pull/32)、③ 日记进向量缓存 [#34](https://github.com/XnneHangLab/wikimem/pull/34) 均已落地；④ recency 衰减项 + 日记参与无窗口检索尚未实现，待 bench 数据（同 ADR-0002 §6）
- **关联**：[ADR-0001](./0001-diary-store.md)（离散判据：事件 vs 状态）、[ADR-0002](./0002-time-range-retrieval.md)（时间门控；§6 recency 衰减项）、[ADR-0004](./0004-api-contract-thin-shells.md)（Python API 是契约）、[ADR-0005](./0005-memorize-injected-llm.md)（memorize 注入式 LLM）、[memU ADR-0006](https://github.com/NevaMind-AI/MemU/blob/main/docs/adr/0006-from-memory-item-category-to-tracked-workspace-memorization.md)（*From Memory Item/Category to a Tracked RecallFile/RecallEntry Store* —— 本决策的对照对象，Accepted 2026-06-30）

## 背景

三件事同时指向同一个问题：**category 与 diary 到底是不是两种东西？**

1. **时间门控（ADR-0002 Phase 2）落地时，读侧的区分事实上已经消失了**：实现把 `DiaryEntry` 适配成 `MemoryItem`，然后 **一条管线** 排两层 —— BM25、min-max 融合、预算裁剪、wiki-link 一跳全部共用。区分只活在适配器之前。
2. **memU 已经走完这一步**：其 ADR-0006 把 Memory Item / Category 整体换成 **RecallFile / RecallEntry** 存储模型，条目下沉为更细的 segment，并支持行级编辑。
3. **日记不在向量缓存里**：开启 embedder 时 wiki 拿融合分、日记只拿 BM25 分。当前实现让日记按归一化 BM25 排（而非折进一个 0 余弦被 `(1-w)` 压死），是**权宜之计**，不是最优解。

于是问题变成：要不要抛开 category / diary 的分别，统一视作 RecallFile —— 只是存储位置与 memorize 方式不同？

## 决策

### 1. RecallFile 是**读侧**的统一抽象

**RecallFile = 一个装着 `##` 块的 markdown 文件；每个 `##` 块是一条 RecallItem（L2 可召回单元）。** `wiki/preferences.md` 与 `diary/2026-07-21.md` 都是 RecallFile（目录改名见 §1.2）。

### 1.1 命名：按**角色**命名，不按**内容类型**

术语从 `Category` / `MemoryItem` 迁移到 **`RecallFile` / `RecallItem`**：

- **"memory" 是内容类型，不是角色。** 将来的 skill 同样是"文件 + 可召回块"，但它**不是记忆**；memory 自身也可能再细分。检索层关心的只是"这块能不能被召回"，所以该用 **Recall** 命名 —— 一个能同时容纳 memory / diary / skill / 未定之物的抽象。
- **`item` 是最小记忆块的唯一叫法** —— 一个词，贯穿所有层。`RecallItem` 因此优于 memU 的 `RecallEntry`：`item` 本就是本项目一以贯之的词（`items()`、`item.name`、"one `##` heading per item"、L2 = item），换成 `entry` 要连带把这些全改一遍，收益为零。
  **推论：`DiaryEntry` 一并改为 `DiaryItem`。** 日记文件是 RecallFile，它的 `##` 块因此就是 RecallItem —— 再叫 `Entry` 会让"同一个概念两个名字"活下来。曾考虑过"Entry 表示写侧形状、Item 表示读侧单元"的分工，**放弃**：那条规则要靠人记，而"最小块一律叫 item"看一眼就懂；本项目一贯偏好后者。
- **`Category` 不是被 `RecallFile` "替换"，而是降级为一种 kind。** 因为按本 ADR，diary 文件也是 RecallFile。准确说法是：**一条 RecallFile 有它的 kind**（状态/wiki，或事件/diary），"category" 作为**通用术语**退休，只在指"状态层那种 RecallFile"时才出现。

命名收敛后的全貌：

| 层 | 名字 | 说明 |
|---|---|---|
| L1 文件 | **RecallFile** | `wiki/preferences.md`、`diary/2026-07-21.md` |
| L1 的 kind | wiki / diary | 决定**写**语义（覆盖 vs 只追加） |
| L2 块 | **RecallItem** | 最小记忆块；写侧特化型 `DiaryItem` 仍带 `date`/`time` |

### 1.2 迁移边界（哪些动、哪些不动）

| | 动不动 | 说明 |
|---|---|---|
| 类型名 `MemoryItem` → `RecallItem`、`DiaryEntry` → `DiaryItem` | ✅ 动 | 纯改名；pre-alpha（`0.1.0.dev0`）正是最便宜的时机 |
| 字段与方法：`.category` → **`.file`**、`categories()` → `files()`、`validate_category()` → `validate_file()` | ✅ 动 | 实现期定：`file` 是 `RecallFile` 的自然简写，`item.file == "preferences"` 读起来顺；比 `.recall_file` 短，也避免在 `WikiLink` 上啰嗦 |
| 概念/文档词汇 `category` → RecallFile | ✅ 动 | EN + zh 全量 |
| **磁盘目录 `category/` → `wiki/`** | ✅ **动** | "category" 这个通用术语既然退休，目录就不该继续叫它。两个目录命名的是 **kind**，而我们的 kind 名一直是 **wiki** 与 **diary**（ADR-0001 通篇如此），`wiki/` + `diary/` 对称且与文档一致 |
| **wiki-link 语法 `[[preferences:likes-the-sea]]`** | ❌ **不动** | 链接里写的是**文件实名**，从来不含 "category" 这个词（文档里的 `[[category:item]]` 只是占位符），因此**链接与既有内容零破坏** |
| `journal.jsonl` 字段、向量缓存键 | ✅ **直接改，不做兼容** | 尚未正式投产，此刻**命名干净优先于历史兼容**。向量缓存本就可删可重建；旧 journal 记录作废（它是审计历史，不是真相） |

改名是**一次性、机械、有测试护栏**的清扫，应当作为**独立 PR**，不与功能改动混在一起。

检索层**只认 RecallFile**，不认它来自哪个原语：一个索引、一个排序、一份 token 预算。ADR-0002 Phase 2 的适配器**正式化**为这个一等概念，而不再是内部 shim。

### 2. **写侧**保留两套语义 —— 这是承重墙，不合并

| | category（状态层） | diary（事件层） |
|---|---|---|
| 写模型 | 同名**覆盖**（last-wins） | **只追加**（append-only） |
| 同名/同分钟重复 | 折叠，后者胜 | **都保留**（两个事件都真实） |
| 时间轴 | 无 | 有（文件名即索引） |
| 写 API | `store.add()` | `diary.append()` |

判据仍是 ADR-0001 那条**离散**的：**「这条记忆有没有『它发生在何时』这个属性」**。

**为什么不能合**：ADR-0001 立这条判据，正是为了修 MoeChat 的坑 —— 它用"重要/永久程度"这种**连续谱**划界，切不出干净边界，两个存储的职责长期糊在一起。**若把写模型也统一成一种，这条判据就没有了落点，MoeChat 的边界模糊会原样回来。**

因此本 ADR 把那句"只是存储位置不同、memorize 方式不同"精确化为：

> **存储位置与 memorize 方式的不同，是写语义不同的结果；而读语义本来就相同，所以该统一的是读侧。**

### 3. 日记纳入向量缓存

日记**应当**被 embedding 覆盖，而且比 wiki 更需要：

- **日记是叙事散文，正是 BM25 的盲区**。"他一句话没说，饭也没怎么吃" ←→ "我那天是不是很沮丧"：零共享词，只有语义匹配能连上。wiki 条目是短事实句、与 query 用词高度重叠，BM25 本来就打得准。**把 embedding 只给 wiki，等于把它花在最不需要的那一半。**
- **成本被"不可变"钉死**：缓存是 content-hash 键控（未变则复用、零 API 调用），而日记 append-only、条目永不改写 —— **每条日记一辈子只嵌入一次**。反倒是 wiki 条目会被反复覆盖重嵌。日记是该缓存的理想负载。
- 覆盖后，融合公式对两层**一视同仁**，时间门控里那条"日记按归一化 BM25 排"的权宜规则可以撤掉。

### 4. 日记仍**只经窗口**进入候选集 —— 与 recency 衰减项**绑定**放开

即便进了向量索引，无时间窗口的 query **暂不**语义召回日记。理由：**没有衰减项，永远在线的日记会淹没状态层** —— 一条三周前印象深刻的晚餐，语义上完全可能碾压今天为真的事实。

因此把这两件事**耦合**起来：**"日记参与无窗口检索"的开关，等 ADR-0002 §6 的 recency 衰减项（`exp(-Δt/τ)`，默认关、待 bench 数据）落地后一起放开。** 需要衰减的场景，正是这个开关想服务的场景。

### 5. `journal.jsonl` 保持 jsonl，**不迁 sqlite**

[openclaw#113233](https://github.com/openclaw/openclaw/pull/113233) 把 JSONL transcript 全部去掉、改为 SQLite-only（删掉约 9.4k 行）。是否效仿？**不。** 因为它的动机在我们这里不成立：

- **它删的是"双系统"，不是"jsonl"本身。** 该 PR 的理由是 JSONL 与 SQLite **并存**所带来的 repair / rotation / snapshot / successor 一整套机器，让"session 归属"难以推理；PR 里**没有**给出任何性能、并发或损坏方面的实测问题。我们不存在双系统：markdown 是唯一真相，journal 是历史，vectors 是派生缓存。
- **它存的是运行时状态，我们存的是追加日志。** 它的 JSONL 承载**活跃会话 transcript** —— 可变、热路径、要压缩要轮转要修复。`journal.jsonl` 只被**追加**，从不修复、不轮转、不压缩，也不在检索热路径上被读。文件格式扛不住的正是前者那种用法。
- **journal 的全部价值就是 `tail -f` 能看。** 迁进 sqlite 会亲手毁掉它唯一的卖点 —— "不需要数据库工具就能回答'我的记忆发生了什么'"。

诚实补两点：`sqlite3` 在 stdlib 里，所以**不算引入依赖**，这不是理由；而且**真正的真相文件（markdown）永远不可能进 sqlite** —— 那是硬约束 3（磁盘上不允许有不可读的真相）的正面违反。

**重新审视的触发条件**：journal 需要被**查询**（"列出条目 X 的全部变更"）、需要**多进程并发写**，或体量大到 `tail` 不再实际。到那时正确的做法多半也是"为 journal 建一个可删除的派生索引"，而不是把 jsonl 换掉。

**openclaw 真正能借鉴的一课**是另一句：**别让同一份数据由两个存储各存一份**。这一课我们本来就在守。

### 6. 粒度维持**块级**（`##`），不做行级 segment

- 条目**本来就小**：memorize 参考提示词明确要求"一条一事件、2–4 句"（ADR-0005）。把一段 3 句话的日记再切碎，切掉的是"一个完整瞬间"这个属性 —— 而那正是日记有灵魂的原因。
- **`##` 是稳定锚点，行号不是**：真相是**人可手改**的 markdown（硬约束 3）。人手插一行，所有行号偏移；`## 14:30` 纹丝不动。content-hash 缓存也建立在稳定块上，行级会让缓存大面积失效。
- 粒度归**宿主写入策略**（ADR-0001 已如此定），不是框架切分。

**重新审视的触发条件**：若 bench 显示"长条目导致召回不准"成为实际问题，优先考虑**按空行切段**这种保守做法，而不是行级。

## 理由

- **读写分开看，两个答案都成立**：召回时它们确实是同一种东西（Phase 2 已验证）；写入时它们确实不是（离散判据是 ADR-0001 的地基）。把问题拆成两层，就不必在"全合"与"全分"之间二选一。
- 统一读侧**消除**了"两条管线、两份预算、两个排序"这类漂移来源，与 ADR-0004"单一契约消除消费者之间行为漂移"同源。
- 日记进向量是把 embedding **花在刀刃上**，且成本因不可变而一次性。

## 后果

**正面**

- 检索层只需理解一个概念（RecallFile），新增第三种原语时无需再动排序/预算/explain。
- 日记的语义召回质量显著提升（散文 × 语义匹配），并撤掉一条权宜规则。
- ADR-0001 的离散判据完好保留，MoeChat 的边界模糊不会回潮。

**负面 / 代价**

- 一次公开契约改名（`MemoryItem` → `RecallItem`、`DiaryEntry` → `DiaryItem`，ADR-0004 意义上的破坏性变更）+ 全量文档词汇迁移。pre-alpha 阶段做最便宜，但**再晚做就会越来越贵**。
- 词汇过渡期内，"category" 一词在旧文档/旧 journal 里仍会出现，读者需要知道它现在指"状态层那种 RecallFile"。
- 向量缓存随日记单调增长（wiki 是有界的，日记不是）；memmap 分层 + 10k 以上二值量化已为此设计，但需在文档里写明增长预期与"删掉即可重建"的兜底。
- "日记参与无窗口检索"被推迟到衰减项之后，短期内无时间意图的 query 仍召不回日记。

**实施**

1. **改名清扫（独立 PR）**：`MemoryItem` → `RecallItem`、`DiaryEntry` → `DiaryItem`；磁盘目录 `category/` → `wiki/`；`journal` 字段与向量缓存键直接改、**不做兼容**；文档词汇全量同步（EN/zh）。wiki-link 语法**不动**。既有 store 的迁移 = 一次 `mv memory/category memory/wiki`，在 CHANGELOG 里写明即可。
2. **形式化 RecallFile**：把 ADR-0002 Phase 2 的适配器提升为一等概念。
   顺带需要定的一件事：Phase 2 目前把日记条目表示为 `category="diary"` + `name="2026-07-21 14:30"`；按 RecallFile 语义，更贴切的是 **RecallFile = `2026-07-21`（那个日文件）、item = `14:30`**。后者概念上更正确，代价是列举 RecallFile 时会看到"一天一个文件"（本来也确实如此）。
3. `rebuild()` 把日记条目一并喂给 `VectorCache.sync()`；撤掉"日记按 BM25 排"的权宜规则；补增长与成本说明。
4. recency 衰减项（ADR-0002 §6）与"日记参与无窗口检索"作为**同一个**里程碑，由 bench 数据决定默认值。
