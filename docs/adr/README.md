# wikimem ADR 索引

wikimem 的架构决策记录（Architecture Decision Records）。

创始设计不在本目录：存储层（categories + wiki-links + journal）、检索管线（BM25 + 可选 embedding 融合）以及三条硬约束，来源于宿主项目的 [XnneHangLab ADR-0001](https://github.com/XnneHangLab/XnneHangLab/blob/dev/docs/adr/0001-llm-mode-memory.md)（记忆管线）与 [XnneHangLab ADR-0002](https://github.com/XnneHangLab/XnneHangLab/blob/dev/docs/adr/0002-memu-design-not-dependency.md)（memU——借鉴设计而非引入依赖）。wikimem 独立成库后，**框架自身的决策记录在这里**；宿主侧的策略决策（意图识别、memorize 策略、情绪、前端）仍记录在 XnneHangLab 的 `docs/adr`。两边编号各自独立，跨仓引用时注明仓库名。

## 继承的硬约束（来自 XnneHangLab ADR-0001）

1. **零基础设施**：没有 embedding 模型、向量库、图数据库时系统必须可用——BM25 兜底，embedding 只是可选增强。
2. **不为记忆等待 LLM**：retrieve 路径 0 次 LLM 调用；memorize 至多 1 次 LLM 调用、异步、由宿主发起。框架本体零 LLM。
3. **磁盘上不允许有不可读的真相**：markdown 文件是唯一事实源；一切索引/向量都是可删除、可重建的派生缓存。

## 索引

| 编号                                    | 标题                                                    | 状态     |
| --------------------------------------- | ------------------------------------------------------- | -------- |
| [0001](./0001-diary-store.md)           | 日记原语 — 事件流与状态层分离                           | Proposed |
| [0002](./0002-time-range-retrieval.md)  | 时间检索 — time_range 门控 + 正则快通道，不做第三路融合 | Proposed |
| [0003](./0003-vectors-cache-metadata.md) | 向量缓存记录 model/dim — 失配警告并降级，而非报错重建   | Proposed |
| [0004](./0004-api-contract-thin-shells.md) | 接口契约 — Python API 是契约，CLI 与 serve 都是薄壳     | Proposed |
| [0005](./0005-memorize-injected-llm.md) | memorize — 注入式 LLM，两种宿主驱动写入（后台抽取 / Agent 工具） | Proposed |

> 0001 / 0002 的完整设计讨论（三种时间融合方案的对比分析）见博客《RRF vs Hybrid Search》（nyakku.moe，撰写中）。
