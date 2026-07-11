# 什么是 wikimem？

wikimem 是面向 AI Agent 的**文件优先记忆管线**：长期记忆以**纯 markdown 文件**
存储（每个分类一个文件，每个 `##` 标题一个条目），用**内存 BM25 索引**检索，
再由 **wiki-links** —— `[[category:item]]` 形式的引用 —— 把关键词搜索够不着的
"含义相关"条目连接起来。

它是一个**零强制依赖**的 Python 库。`pip install wikimem` 就是完整系统：
存储、检索（含中文，字符 bigram 兜底）、wiki-link 展开、追加式 journal。

## 它解决什么问题

"Agent 记忆"通常以基础设施的形态出现：相似度要一个向量数据库，embedding 端点
成了硬依赖，关系还要再上一个图数据库，最后用 docker-compose 把它们捆在一起。
对个人 Agent 来说 —— 数据量是几千条，不是几十亿条 —— 这套栈是头重脚轻的：
基础设施比数据本身还重，数据离开工具就没法读，而每多一层就多一种丢记忆的方式。

wikimem 把它倒了过来。记忆**就是**一个 markdown 文件夹。其余一切 —— BM25
索引、可选的向量缓存 —— 都是派生状态，随时可以删掉、随时能从文件重建。
本项目的前代设计跑着 mem0 + Qdrant + Neo4j 才做到这个文本文件夹做的事；
图数据库当年买的关联召回，wiki-links 用一次机械的一跳展开就交付了。

## 四条设计规则

库里的一切都从这四条推导而来（XnneHangLab ADR-0001 定稿）：

1. **markdown 文件是唯一事实源。** 每个分类一个文件（`memory/preferences.md`），
   每个 `##` 标题一个条目。可以直接阅读、编辑、diff —— 你的编辑器就是管理界面。
2. **磁盘上没有不可读的真相。** 一切派生产物（索引、向量缓存）都可删除、
   可从文件重建。BM25 索引在启动时于内存中构建，永不落盘。
3. **永不阻塞对话。** 检索是同步的、有 token 预算的、fail-open 的，
   **0 次 LLM 调用**；记忆写入由宿主异步执行，每轮至多 **1 次** LLM 调用。
4. **"发生了什么"永远可以回答。** 每次变更向 `journal.jsonl` 追加一行；
   检索可以解释自己的打分。

## 一条管线，没有模式

不存在需要选择的"配置模式"。wikimem 只有一条管线；extras 只是解锁可选增强：
装了就自动生效、彼此之间不冲突：

| 安装方式 | 增加什么 | 使用场景 |
|---|---|---|
| `wikimem` | 无 —— 零依赖 | 功能完整：存储、BM25 检索（中文用字符 bigram）、wiki-links、journal |
| `wikimem[zh]` | jieba | 中文关键词召回比 bigram 更准 —— 装上即自动启用，无需任何配置 |
| `wikimem[embed]` | httpx + numpy | 语义召回（按含义而不是词面匹配）—— 只有传入 `embedder` 才会启用；端点挂了自动回退 BM25 |
| `wikimem[all]` | 以上全部 | "别让我做选择"选项 |

全部装上也不会改变任何行为，直到你真正用到它：分词器在 jieba 可导入时自动采用；
embedding 路径只在构造 `MemoryIndex` 时传入 `embedder` 才会运行。

## wikimem 不是什么

- **不是向量数据库。** 有一个可选的向量*缓存*，但它是派生状态 ——
  可删除、可重建、永远不是事实源。
- **不是图数据库。** "图"就是文本：条目内容里的 wiki-links。
  展开是一次按名字的精确查找，不是图遍历引擎。
- **不是笔记软件。** 格式刻意向 Obsidian *靠拢*（markdown + `[[...]]`），
  但基本单元是几句话规模的**条目**而非整篇文档，而且写入者通常是抽取 LLM，
  不是人。
- **不是 Agent 框架。** wikimem 对你的 LLM、prompt、事件循环没有任何意见。
  接线是宿主的事 —— 见[宿主集成](/zh/guide/host-integration)。

## 状态

Pre-alpha（`0.1.0.dev0`），对照 XnneHangLab ADR-0001 按里程碑逐步构建：

- **M1 ✅ —— 存储层**：分类文件、条目模型 + 溯源元数据、wiki-link 解析、
  `journal.jsonl`、原子写入
- **M2 ✅ —— 检索**：内存 BM25（字符 bigram 兜底，`[zh]` extra 提供 jieba）、
  一跳 wiki-link 展开、token 预算、explain
- **M3 ✅ —— embedding 融合**（`[embed]` extra）：内容哈希向量缓存
  （版本化 `.npy` + 明文 keys）、memmap 分层（1 万条以上二值量化）、
  可插拔 `VectorIndex` 端口、端点不可用时静默回退纯 BM25
- **M4 —— CLI**（下一步）：`ls / show / grep / explain / graph`

## 许可与致谢

Apache-2.0。抽取 prompt 的设计借鉴自
[memU](https://github.com/NevaMind-AI/memU)（Apache-2.0）—— 借鉴设计而非引入
依赖（lab ADR-0002）。BM25 + 余弦的融合公式与 memU ADR-0007 收敛到的一致。
