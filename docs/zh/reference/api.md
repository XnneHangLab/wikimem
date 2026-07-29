# 核心 API

以下一切都从顶层包导入，零依赖安装即可用：

```python
from wikimem import (
    MemoryStore, MemoryIndex, Journal, Diary,
    MemoryItem, DiaryEntry, WikiLink, RetrievalResult, RetrievedItem,
    tokenize, est_tokens, parse_wiki_links,
    validate_category, sanitize_item_name,
)
```

可选的 embedding 层住在 `wikimem.vectors`，[单独成页](/zh/reference/vectors)
—— 它刻意**不**在这里重导出，`import wikimem` 永远碰不到 numpy。

## MemoryStore

```python
MemoryStore(root: Path | str)
```

对 store 里 wiki 分类的读写入口，分类文件落在 `root / "category/"`。
构造 store 不触碰文件系统；目录在首次写入时出现。store 自带一个位于
`root / "journal.jsonl"` 的 [`Journal`](#journal)，并通过
[`store.diary`](#diary) 暴露事件流原语（与该 journal 共用）。

### 读

读取**刻意宽容** —— 手改过的文件绝不能让读崩溃
（精确解析规则见[磁盘格式](/zh/reference/file-format)）。

| 方法 | 返回 |
|---|---|
| `categories()` | 排序后的分类名 —— `root / "category/"` 下每个 `*.md` 一个 |
| `items(category=None)` | 全部条目，或某一分类的 |
| `get(category, name)` | 条目或 `None`（比较前先做空白归一） |

### 写

写入**严格**（名字校验）且**原子**（每个分类文件走临时文件 + `os.replace`），
每次变更追加一行 journal。

```python
store.add(
    "preferences",            # 分类：小写 slug（会校验）
    "likes-the-sea",          # 条目名（会清洗）
    "喜欢海边。[[daily_life:beach-trip-plan]]",
    owner="user:xnne",        # 可选溯源
    source_conv="conv_001",   # 可选溯源
    ts=None,                  # 可选 ISO-8601；默认当前 UTC 时间
) -> MemoryItem
```

- `add` **插入或替换**：同名条目会被覆盖，journal 记 `update` 而非 `add`。
  更新模型就这一条 —— 没有单独的 `update()`。
- `remove(category, name, *, owner=None) -> bool` —— 名字不存在返回 `False`。
  删掉分类的最后一条时，文件一并删除。
- 分类 slug 非法或条目名含保留字符时抛 `ValueError`。内容存储时 `strip()`。

### `revision`

整数，每次**进程内**写入成功后递增；`MemoryIndex` 据此惰性重建。
进程外的文件修改不会递增它 —— 那之后调用 `index.rebuild()`。
日记写入**不会**递增它 —— wiki 的 BM25 索引不覆盖 diary 文件。

## Diary

```python
store.diary            # -> Diary，惰性构造，与 store 共用 journal
Diary(root, *, journal=None)   # 也可独立构造
```

**事件流**原语（ADR-0001）：wiki 是状态层（"现在为真的事"），diary 是
事件层（"发生过的事，以及何时"）。条目以 `## HH:MM` 小节落在按天文件
`root / "diary" / "YYYY-MM-DD.md"` 里，序列化与 wiki 条目相同（精确规则见
[磁盘格式](/zh/reference/file-format#日记文件-diary)）。

### 写

```python
store.diary.append(
    "他说换了工作，语气很兴奋。[[work:current-job]]",
    ts=None,          # 可选 ISO-8601 时刻；默认现在（UTC）
    date=None,        # 可选 YYYY-MM-DD；默认 ts 在 tz 下的日历日
    time=None,        # 可选 HH:MM；     默认 ts 在 tz 下的墙钟
    owner=None,       # 可选溯源
    source_conv=None, # 可选溯源
    tz=None,          # 默认 date/time 所用时区（默认系统本地）
) -> DiaryEntry
```

**Append-only** —— 这是唯一写接口。刻意不提供改写/删除：条目只追加，
journal 每条记一行 `diary`。同分钟可有两条事件，都保留（与 wiki 的
last-wins 相反）。内容为空，或 `date` / `time` / `ts` 格式非法时抛
`ValueError`。

### 读

| 方法 | 返回 |
|---|---|
| `day(date)` | 某一 `YYYY-MM-DD` 的全部条目，按文件（时间）顺序 |
| `window(start, end)` | 闭区间 `[start, end]` 日期范围内的全部条目，按时间序（边界反了会自动交换） |
| `dates()` | 所有有文件的日期，升序 |

`ts` 存为归一化后的 UTC ISO-8601 秒精度字符串；`date` / `time` 是人本地的
日历日与墙钟。非法 `ts` 会抛 `ValueError`（不会静默回退到"现在"）。
`window` 是 [ADR-0002](/adr/0002-time-range-retrieval) 时间门控所依赖的
O(天数) 文件集查找 —— 日记只给区间、不做打分。

## Memorize

```python
memorize(
    diary, turn, *,
    llm,                          # 你的 LLM（见下面的端口）
    character="the assistant",    # 会插进提示词
    prompt=None,                  # 整份替换 DIARY_PROMPT
    owner=None, source_conv=None, # 溯源信息，透传给 append
    **append_kwargs,              # 如 date= / time= / ts=
) -> list[DiaryEntry]
```

用**一次** LLM 调用把一轮对话变成日记条目：跑提示词 → 解析 → 落盘。提示词、解析、
校验归框架；LLM 归宿主（ADR-0005）。返回已写入的条目 —— 没什么值得记时返回 `[]`，
这是常见且健康的结果。

**Fail-open**：会剥掉 ``` 代码围栏、接受单个对象；散文或坏 JSON 一律返回 `[]`，
不抛异常。完整提示词与接法见[《写日记》](/zh/guide/writing-diary)。

### `LLM` 端口

```python
class LLM(Protocol):
    def chat(self, messages: list[dict[str, str]]) -> str: ...
```

`chat_completion` 形状、**同步** —— 所有 provider 与网关都认的那一种协议，也是能
工作的最小接口。wikimem 不构造客户端、不持有 key、不挑 provider；你用手头已有的
客户端实现 `chat()` 即可。异步调度归宿主：把 `memorize()` 丢进后台任务，别挡住对话。

### `DIARY_PROMPT`

随包提供的参考提示词（英文指令；条目用**对话本身**的语言书写）。用 `prompt=`
按次覆盖 —— 正因为有这一个参数，框架只需发一份默认值，而不必维护「每语言一份」的矩阵。

## 命名助手

```python
validate_category(category: str) -> str    # 非法时抛 ValueError
sanitize_item_name(name: str) -> str       # 非法时抛 ValueError
```

- **分类**必须匹配 `[a-z0-9_][a-z0-9_-]*` —— 小写 ASCII slug，
  因为它同时充当文件名和链接前缀。
- **条目名**可为任何语言；连续空白折叠成单个空格；拒绝
  `[[`、`]]`、`:`、`|`、`#`（它们会破坏标题、链接或元数据）。

## MemoryItem / DiaryEntry / WikiLink

```python
@dataclass
class MemoryItem:                   # wiki：检索单元（状态）
    category: str
    name: str
    content: str
    owner: str | None = None        # 手写条目为 None —— 容忍
    source_conv: str | None = None
    ts: str | None = None           # ISO-8601 UTC 字符串

    @property
    def links(self) -> list[WikiLink]   # 访问时从 content 现解析
```

```python
@dataclass
class DiaryEntry:                   # diary：一条事件（与 MemoryItem 并列）
    date: str                       # YYYY-MM-DD —— 天文件
    time: str                       # HH:MM —— 标题（人本地墙钟）
    content: str
    owner: str | None = None
    source_conv: str | None = None
    ts: str | None = None           # ISO-8601 UTC 时刻

    @property
    def links(self) -> list[WikiLink]   # 与 MemoryItem 同一套 wiki-link 解析
```

```python
@dataclass(frozen=True)
class WikiLink:
    category: str
    name: str
    def render(self) -> str    # "[[category:name]]"
```

`parse_wiki_links(text: str) -> list[WikiLink]` 按出现顺序抽取链接；
残缺链接被忽略，不报错。

## MemoryIndex

```python
MemoryIndex(
    store: MemoryStore,
    *,
    use_jieba: bool | None = None,     # None = 自动检测 [zh] extra
    embedder = None,                   # 传入即启用融合 —— 见向量 API
    vectors_dir: Path | str | None = None,  # 向量缓存位置，默认 store 根目录
    fusion_weight: float = 0.5,        # 融合分中 BM25 的权重
    binary_threshold: int = 10_000,    # memmap 分层阈值 —— 见向量 API
)
```

架在 `MemoryStore` 之上的 BM25（+ 可选 embedding 融合）。BM25 索引是内存
派生状态：首次使用时构建，`store.revision` 变化后自动重建，永不落盘。

- `rebuild()` —— 立刻重扫 store。仅在进程外改过文件后需要；
  个人记忆规模下很便宜。
- `retrieve(query, *, limit=10, budget_tokens=None, expand_links=True,
  explain=False, time_range=None, tz=None) -> RetrievalResult` —— 排序、一跳
  展开、按预算裁剪。0 次 LLM 调用、同步、embedding 路径降级不抛错。
  语义详见[检索](/zh/guide/retrieval)。

### 时间门控

```python
index.retrieve("前天晚上吃了什么")                              # 窗口由 query 自己解析
index.retrieve("吃了什么", time_range=("2026-07-22", "2026-07-22"))  # 或显式传入
```

窗口把那几天的**日记**条目带进与 wiki **同一个**排序。时间**只过滤候选、不参与
打分**，因此融合公式原样不动（ADR-0002）。

| 参数 | 含义 |
|---|---|
| `time_range` | 闭区间 `("YYYY-MM-DD", "YYYY-MM-DD")`。这是宿主意图识别 / tool call 的出口 |
| `tz` | 相对表达按哪个日历解析（默认系统本地，与日记文件的命名一致） |

- **两条来路**：显式传 `time_range`，或让**正则快通道**从 query 里找
  （`昨天` / `前天` / `上周三` / `3天前` / `7月21号` / ISO 日期 —— 见
  [`parse_time_range`](#parse-time-range)）。它刻意**宁窄勿误**：解析不出就是
  **无时间意图**，绝不猜。
- **wiki 永不被时间过滤**：时间轴只属于日记，状态层继续参与竞争。所以"海边"能
  同时召回*那天去海边的事件*和*喜欢海边这条偏好*。
- **query 为空 + 有窗口** → 按时间倒序返回该窗口（不用关键词也能回忆某一天）。
- **窗口内为空会自动放宽**一天再取，而不是回答"没有"，并如实标注
  （`time_range_widened`）。
- **没有窗口时行为与从前完全一致**，日记根本不进入检索。

## RetrievalResult

| 字段 | 类型 | 含义 |
|---|---|---|
| `items` | `list[RetrievedItem]` | 预算内幸存者，注入顺序 |
| `budget_tokens` | `int \| None` | 生效的上限（`None` = 不设限） |
| `budget_used` | `int` | `items` 的估算 token 总量 |
| `embedding_used` | `bool` | 仅当余弦路径真的跑了才为 `True` |
| `dropped` | `list[RetrievedItem]` | 被预算裁掉的 —— 仅 `explain=True` 时填充 |
| `unresolved_links` | `list[str]` | 目标缺失的链接原文，如 `"[[a:b]]"` |
| `time_range` | `tuple[str, str] \| None` | 实际生效的窗口（`None` = 未开门控） |
| `time_range_source` | `str \| None` | `"explicit"`（你传的）或 `"parsed"`（正则快通道） |
| `time_range_widened` | `bool` | 窗口内为空，已向两侧各放宽一天 |

经门控浮现的日记条目会以 `RecallItem` 的形态出现：`file="diary"`、
`name="YYYY-MM-DD HH:MM"` —— 因此它和任何条目一样参与排序、链接展开与预算裁剪。

## RetrievedItem

| 字段 | 类型 | 含义 |
|---|---|---|
| `item` | `MemoryItem` | 记忆本体 |
| `source` | `str` | `"hit"`（搜索命中）或 `"link"`（一跳展开） |
| `score` | `float \| None` | 排序分：跑了 embedding 是融合分，否则 BM25；链接条目为 `None` |
| `bm25_score` | `float \| None` | 原始 BM25 分量（仅命中） |
| `cos_score` | `float \| None` | 原始余弦分量（仅命中且融合已跑） |
| `via` | `str \| None` | 链接条目：把它拉进来的命中名 |
| `matched_terms` | `list[str]` | 该条目中出现的 query 词（已排序） |
| `tokens_est` | `int` | 该条目占用的预算 |

## Journal

```python
Journal(path: Path | str)

journal.append(action, *, category, name,
               owner=None, source_conv=None, detail=None)   # wiki 变更
journal.append_diary(*, date, time, owner=None, source_conv=None)  # diary 追加
journal.entries() -> list[dict]
```

追加式 JSONL 日志，两个原语共用。`MemoryStore` 自动写它（`add` / `update` /
`remove`），`Diary.append` 写 `diary` 行 —— 很少需要自己构造。行格式见
[磁盘格式](/zh/reference/file-format#journal-jsonl)。

## parse_time_range

```python
parse_time_range(text, *, tz=None, today=None) -> tuple[str, str] | None
```

[时间门控](#时间门控)背后的正则快通道：把时间表达变成闭区间
`("YYYY-MM-DD", "YYYY-MM-DD")` 窗口；没有就返回 `None`。纯 stdlib ——
不引 `dateparser` / `arrow` / `TimeNLP`。

覆盖：`今天` `昨天` `前天` `大前天` `明天` `后天`、`N天前`（含 `三天前`）、
`N days ago`、`上周三` / `这周五`、`上周` / `这周`、`N周前`、`上个月` / `这个月`、
`2026-07-21`、`2026/7/1`、`7月21号`。英文 `today` / `yesterday` / `tomorrow`
需要词边界。

**宁窄勿误**：`最近`、`前几天`、`以前` 这类没有可辩护边界的表达**故意**返回
`None`。错窗口会**静默藏起**正确的记忆，比不开窗更糟 —— 调用方根本不知道搜索
被过滤了。正则是框架的地板；能听懂"我们吵架那天"的宿主 LLM 是天花板，它直接传
`time_range=`。

`today=` 可钉住"现在"，用于确定性测试或宿主自带时钟。

## 分词

```python
tokenize(text: str, *, use_jieba: bool | None = None) -> list[str]
```

小写拉丁词（`[a-z0-9]+`）加 CJK 处理：默认字符 bigram，`[zh]` extra
可导入时用 jieba。`use_jieba=None` 自动检测；`True` 强制 jieba
（缺席时仍回退 bigram）；`False` 强制 bigram —— 适合可复现的基准。

```python
est_tokens(text: str) -> int
```

粗糙的 LLM token 估算：拉丁词一个、CJK 字符一个。用于预算裁剪 ——
**稳定比精确重要** —— 不适合拿去算账。
