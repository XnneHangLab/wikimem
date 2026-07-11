# 核心 API

以下一切都从顶层包导入，零依赖安装即可用：

```python
from wikimem import (
    MemoryStore, MemoryIndex, Journal,
    MemoryItem, WikiLink, RetrievalResult, RetrievedItem,
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

对一个分类 markdown 文件目录的读写入口。构造 store 不触碰文件系统；
目录在首次写入时出现。store 自带一个位于 `root / "journal.jsonl"` 的
[`Journal`](#journal)。

### 读

读取**刻意宽容** —— 手改过的文件绝不能让读崩溃
（精确解析规则见[磁盘格式](/zh/reference/file-format)）。

| 方法 | 返回 |
|---|---|
| `categories()` | 排序后的分类名 —— `root` 下每个 `*.md` 一个 |
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

## 命名助手

```python
validate_category(category: str) -> str    # 非法时抛 ValueError
sanitize_item_name(name: str) -> str       # 非法时抛 ValueError
```

- **分类**必须匹配 `[a-z0-9_][a-z0-9_-]*` —— 小写 ASCII slug，
  因为它同时充当文件名和链接前缀。
- **条目名**可为任何语言；连续空白折叠成单个空格；拒绝
  `[[`、`]]`、`:`、`|`、`#`（它们会破坏标题、链接或元数据）。

## MemoryItem / WikiLink

```python
@dataclass
class MemoryItem:
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
  explain=False) -> RetrievalResult` —— 排序、一跳展开、按预算裁剪。
  0 次 LLM 调用、同步、embedding 路径降级不抛错。
  语义详见[检索](/zh/guide/retrieval)。

## RetrievalResult

| 字段 | 类型 | 含义 |
|---|---|---|
| `items` | `list[RetrievedItem]` | 预算内幸存者，注入顺序 |
| `budget_tokens` | `int \| None` | 生效的上限（`None` = 不设限） |
| `budget_used` | `int` | `items` 的估算 token 总量 |
| `embedding_used` | `bool` | 仅当余弦路径真的跑了才为 `True` |
| `dropped` | `list[RetrievedItem]` | 被预算裁掉的 —— 仅 `explain=True` 时填充 |
| `unresolved_links` | `list[str]` | 目标缺失的链接原文，如 `"[[a:b]]"` |

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
               owner=None, source_conv=None, detail=None)
journal.entries() -> list[dict]
```

追加式 JSONL 日志。`MemoryStore` 自动写它（`add` / `update` / `remove`），
很少需要自己构造。行格式见
[磁盘格式](/zh/reference/file-format#journal-jsonl)。

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
