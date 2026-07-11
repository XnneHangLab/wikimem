# 快速上手

## 安装

```bash
pip install wikimem        # 默认安装 —— 开箱即用，功能完整
pip install "wikimem[all]" # 不想纠结就装这个，可选增强全都带上
```

要求 Python ≥ 3.11。基础安装**零依赖**；`[zh]` 和 `[embed]` 各自解锁什么见
[extras 一览表](/zh/guide/what-is-wikimem#一条管线-没有模式)。

## 写入第一批记忆

```python
from wikimem import MemoryStore

store = MemoryStore("memory/")

store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")
store.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")
```

`add` 要么插入新条目，要么替换同名旧条目 —— 更新模型就这么一条。
看看它写下了什么：

```markdown
<!-- memory/preferences.md -->
# preferences

## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | source=conv_20260710 | ts=2026-07-10T03:00:00+00:00 -->
```

分类是一个 markdown 文件；条目是一个 `##` 小节；溯源信息放在一条 HTML 注释里；
`[[daily_life:beach-trip-plan]]` 这条 wiki-link 就是内容中的纯文本。
读这份文件不需要 wikimem。

::: tip 命名规则
分类名是小写 ASCII slug（`daily_life`、`preferences`）—— 它同时充当文件名和
链接前缀。条目名可以是任何语言，但不能含 `[[ ]] : | #`。精确规则见
[磁盘格式](/zh/reference/file-format)。
:::

## 检索

```python
from wikimem import MemoryIndex

index = MemoryIndex(store)  # 内存 BM25，store 写入后自动重建
result = index.retrieve("想去海边玩", budget_tokens=800)

for entry in result.items:
    print(entry.source, entry.item.name, entry.score, entry.matched_terms)
# hit  likes-the-sea    3.87  ['海边', '想去', ...]
# link beach-trip-plan  None  []
```

刚才发生了三件事，全程没有一次 LLM 调用：

1. **BM25 排序**：每个条目对 query 打分（中文默认按字符 bigram 分词，
   装了 jieba 则用 jieba）。
2. 每个命中的 wiki-links 被**一跳展开**：`likes-the-sea` 链到
   `beach-trip-plan`，于是完整的目标条目跟着注入，标记为 `source="link"`。
3. 整个序列按 token 预算（`budget_tokens=800`）**裁剪**，注入顺序保持
   "命中后面紧跟它的链接目标"。

`result` 还会告诉你 `budget_used`、哪些链接没解析成功（`unresolved_links`），
以及 —— 传 `explain=True` 时 —— 到底裁掉了什么。细节见[检索](/zh/guide/retrieval)。

## 磁盘上有什么

```
memory/
├── preferences.md    ← 事实源
├── daily_life.md     ← 事实源
└── journal.jsonl     ← 追加式审计日志，一行一次变更
```

基础管线持久化的东西就这些。BM25 索引住在内存里，启动时从文件重建 ——
没有要迁移的、要备份的、会损坏的状态。如果启用
[embedding 融合](/zh/guide/embedding-fusion)，markdown 旁边会多出一个向量缓存
（`vectors-*.npy` + `vectors.keys.jsonl`）—— 它是缓存，随时删都是安全的。

## 直接手改文件

文件是你的。在编辑器里改错别字、删掉尴尬的条目、手工补一条 wiki-link ——
读取被刻意做得宽容，手改永远不会让管线崩溃。两件事需要知道：

- store 只在**自己的**写入上递增内部 revision，索引据此惰性重建。
  **进程之外**的修改（编辑器、git checkout）要靠调用 `index.rebuild()`
  被感知 —— 或者干脆重启，反正索引本来就在启动时重建。
- 手改时如果重复了同名 `##` 标题，读取按**最后一个为准**；
  下次写该分类时重复项自动消失。

## 下一步

- [Wiki-links](/zh/guide/wiki-links) —— 取代图数据库的那个点子
- [检索](/zh/guide/retrieval) —— 打分、预算、explain 的完整细节
- [Embedding 融合](/zh/guide/embedding-fusion) —— 可选的语义召回
- [宿主集成](/zh/guide/host-integration) —— 把 wikimem 接进 Agent
