# CLI

包内自带零依赖命令行工具（纯 stdlib——无 docker、无服务进程），在 shell 里直接查看一个 store：

```bash
wikimem --store ./memory <command>    # 或者：python -m wikimem
```

`--store` / `-s` 默认读 `WIKIMEM_STORE` 环境变量，其次是当前目录。

退出码遵循 shell 惯例：`0` 成功，`1` 无匹配 / 不存在，`2` 用法或 store 错误。

## `ls`

列出 categories 与条目数：

```
$ wikimem -s ./memory ls
daily_life      1
preferences     2
```

## `show <category> [name]`

按文件存储的原样打印一个 category（或单个条目）——标题、内容、溯源注释：

```
$ wikimem -s ./memory show preferences likes-the-sea
## likes-the-sea

喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]

<!-- wikimem: owner=user:xnne | ts=2026-07-10T03:00:00+00:00 -->
```

## `grep <pattern> [-i]`

对条目名与内容做正则搜索，输出带 `category:name` 前缀（grep 风格）：

```
$ wikimem -s ./memory grep 海边
preferences:likes-the-sea:喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]
daily_life:beach-trip-plan:计划夏天去海边旅行，看日出。
```

## `explain "<query>"`

跑一次真实检索（`MemoryIndex.retrieve(..., explain=True)`）并打印打分明细：命中排序、一跳 wiki-link 展开及其来源、token 估算、预算裁剪、悬空链接。

```
$ wikimem -s ./memory explain "想去海边玩"
query: 想去海边玩
query tokens: 想去, 去海, 海边, 边玩
ranking: BM25 (embedding: off)

  #  src      score     bm25    cos  ~tok  item
  1  hit     1.676    1.676      -     22  preferences:likes-the-sea  [去海, 海边, ...]
  2  link        -        -      -     15  daily_life:beach-trip-plan  (via likes-the-sea)

budget: used 37 / no limit
unresolved links: [[missing:gone]]
```

参数：`--limit N`（命中上限，默认 10）、`--budget N`（token 预算——被裁掉的条目会列出）、`--no-links`（关闭一跳展开）、`--jieba` / `--no-jieba`（强制 CJK 分词路径，默认自动）。

CLI 始终走 BM25 路径——embedding 融合需要配置端点，属于宿主配置，不属于 shell 查看场景。

## `graph [--format mermaid|json]`

从 markdown 中解析 `[[category:item]]`，导出 wiki-link 关系图。这就是 Neo4j 语义层可视化退役后的接替者：零基础设施，同一张图。

```
$ wikimem -s ./memory graph
graph LR
    n0["daily_life:beach-trip-plan"]
    n1["preferences:likes-the-sea"]
    n2["missing:gone"]:::unresolved
    n1 --> n0
    n1 --> n2
    classDef unresolved stroke-dasharray: 5 5;
```

mermaid 输出可直接粘进任何 markdown 渲染器。store 中不存在的链接目标会保留为虚线 `unresolved` 节点，悬空引用一眼可见。

`--format json` 输出 `{"nodes": [...], "edges": [...]}`（节点字段：`id` / `category` / `name` / `unresolved`），宿主前端可自行渲染。
