# 磁盘格式

wikimem 持久化的一切都以"人能读"为第一设计目标（多数还能直接手写）。
一个完整的记忆目录：

```
memory/
├── preferences.md        ← 事实源（每个分类一个文件）
├── daily_life.md         ← 事实源
├── journal.jsonl         ← 追加式审计日志
├── vectors-000003.npy    ← 派生：向量缓存（仅 [embed]）
└── vectors.keys.jsonl    ← 派生：缓存键映射（仅 [embed]）
```

**删除安全性口诀：** `.md` 文件就是记忆；其余都可以随时删掉、自动重建
（journal 是历史 —— 删了丢审计轨迹，不丢任何记忆；BM25 索引根本不落盘）。

## 分类文件

每个分类一个 markdown 文件，每个条目一个 `##` 小节：

```markdown
# preferences

## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->

## 手冲咖啡

只喝手冲咖啡，从不加糖。
```

每个条目的序列化顺序：`## 名字` 标题、空行、内容（存储时已 strip）、空行，
以及 —— 仅当任一溯源字段存在时 —— 元数据注释。

### 命名

- **分类** = 文件名主干 = 链接前缀。必须匹配 `[a-z0-9_][a-z0-9_-]*`
  （小写 ASCII slug）。写入时强制校验。
- **条目名** = 标题文本 = 链接目标。任何语言均可；连续空白折叠为一个空格；
  不得包含 `[[`、`]]`、`:`、`|`、`#`。写入时强制校验。

### 元数据注释

```
<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->
```

- 字段是以 `|` 分隔的 `key=value` 对；识别的键：`owner`、`source`
  （映射为 `MemoryItem.source_conv`）、`ts`（ISO-8601 UTC）。
- 所有字段可选；全空时整条注释省略。
- 因为 `|` 是分隔符，owner/source 值里的字面 `|` 在写入时被替换为 `/`。

### 读取宽容度（欢迎手改）

读取刻意宽松 —— 下面这些是**保证**，不是巧合：

| 你干了这个 | wikimem 这样处理 |
|---|---|
| 手写条目、没带元数据注释 | 没问题 —— `owner`/`source_conv`/`ts` 为 `None` |
| 重复了同名 `##` 标题 | 最后一个为准；下次写该分类时收敛 |
| 第一个 `##` 之前留了文字 | 忽略（文件标题/前言不属于任何条目） |
| 元数据注释写坏了 | 当普通内容对待，不报错 |
| 改名/删除了链接目标 | 链接悬空：展开时跳过，记入 `unresolved_links` |

写入是严格的一侧：每次变更校验名字、整文件重写（临时文件 + 原子
`os.replace`）、追加一行 journal。删除分类最后一条时，文件一并删除。

::: warning 进程外修改
手改不会递增 store 的 revision 计数器 —— 运行中的 `MemoryIndex` 要等你调用
`rebuild()` 才能看见（或者重启进程；索引在内存里，启动时本来就会重建）。
:::

## Wiki-link 语法

条目内容里的 `[[category:name]]`。category 取到**第一个**冒号为止；
两侧都不能含 `[`、`]`、`:` 或换行；首尾空白会被去掉；残缺链接被解析器忽略。
动机与行为：[Wiki-links](/zh/guide/wiki-links)。

## journal.jsonl

一行一个 JSON 对象，每次变更追加 —— `tail -f journal.jsonl` 就是
"我的记忆发生了什么"的实时答案：

```json
{"ts": "2026-07-10T03:00:00+00:00", "action": "add", "category": "preferences", "item": "likes-the-sea", "owner": "user:xnne", "source_conv": "conv_20260710"}
{"ts": "2026-07-10T03:05:12+00:00", "action": "update", "category": "preferences", "item": "likes-the-sea", "owner": "user:xnne"}
{"ts": "2026-07-10T04:11:40+00:00", "action": "remove", "category": "daily_life", "item": "beach-trip-plan"}
```

| 字段 | 出现 | 含义 |
|---|---|---|
| `ts` | 恒有 | ISO-8601 UTC，秒级精度 |
| `action` | 恒有 | `add` \| `update`（同名替换）\| `remove` |
| `category`、`item` | 恒有 | 动到了什么 |
| `owner`、`source_conv`、`detail` | 提供时 | 溯源 / 自由备注 |

非 ASCII 原样存储（`ensure_ascii=False`）—— journal 是给 pager 直接读的，
不是给人解码的。

## 向量缓存（`[embed]` extra）

派生状态，但有一点不同：向量重算要花 embedding API 的钱，所以不像 BM25
索引那样每次重建，而是持久缓存 —— 即便如此它也**永远不是事实源**，
两个文件随时删都安全。

### `vectors.keys.jsonl`

纯文本，让"谁对应谁"始终可读：

```json
{"vectors_file": "vectors-000003.npy"}
{"category": "preferences", "name": "likes-the-sea", "hash": "9f8a…"}
{"category": "daily_life", "name": "beach-trip-plan", "hash": "b774…"}
```

头一行指明当前矩阵文件；之后按矩阵行序一行一条。`hash` 是被 embed 文本
（`name\ncontent`）的 sha256 —— 增量同步的钥匙（哈希没变 = 不发 API 请求）。

### `vectors-NNNNNN.npy`

float32 矩阵，与 key 行一一对应，memory-map 加载。带版本号后缀是因为
**Windows 不允许替换仍被活索引 memory-map 的文件** —— 每次 sync 写新版本、
尽力删除旧版本（清不掉的留给后续 sync 收拾）。

撕裂状态 —— 有 keys 没矩阵、或行数对不上 —— 一律按"没有缓存"处理，
下次 sync 重建。损坏数据从不被信任。
