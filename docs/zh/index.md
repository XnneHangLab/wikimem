---
layout: home

hero:
  name: wikimem
  text: 面向 AI Agent 的文件优先记忆
  tagline: 纯 markdown 之上的 categories + wiki-links。不需要数据库、不需要 embedding 模型、不需要 docker —— pip install wikimem 即可使用。
  image:
    src: /logo.svg
    alt: wikimem
  actions:
    - theme: brand
      text: 快速上手
      link: /zh/guide/getting-started
    - theme: alt
      text: 什么是 wikimem？
      link: /zh/guide/what-is-wikimem
    - theme: alt
      text: GitHub
      link: https://github.com/XnneHangLab/wikimem

features:
  - icon: 📄
    title: markdown 就是数据库
    details: 每个分类一个文件，每个 ## 标题一个条目。可以直接阅读、编辑、git diff —— 你的编辑器就是管理界面。
  - icon: 🔗
    title: 链接召回搜索够不着的记忆
    details: "记忆写入时留下的 [[category:item]] 链接，把词面毫无重合的相关条目连起来。展开是机械的一跳查找 —— 不调 LLM，没有图数据库。"
  - icon: 🔍
    title: 零依赖 BM25
    details: 纯内存索引，启动时免费重建。中文开箱即用（字符 bigram），装 [zh] 获得 jieba 分词。
  - icon: 🧭
    title: 语义融合，严格可选
    details: "[embed] extra 把 BM25 与余弦相似度融合。BM25 从不关闭 —— 端点挂了，检索照常工作。"
  - icon: ⚡
    title: 永不阻塞对话
    details: 检索同步、有 token 预算、0 次 LLM 调用；记忆写入异步执行，宿主至多花 1 次 LLM 调用。
  - icon: 🧾
    title: 发生了什么，永远可以回答
    details: 每次变更向 journal.jsonl 追加一行；每次检索都能解释自己的打分。tail -f 就是你的可观测性平台。
---

## 六十秒尝鲜

```python
from wikimem import MemoryIndex, MemoryStore

store = MemoryStore("memory/")
store.add("preferences", "likes-the-sea",
          "喜欢海边，提到过想去海边玩。[[daily_life:beach-trip-plan]]",
          owner="user:xnne", source_conv="conv_20260710")
store.add("daily_life", "beach-trip-plan", "计划夏天去海边旅行，看日出。")

index = MemoryIndex(store)  # 内存 BM25，store 写入后自动重建
result = index.retrieve("想去海边玩", budget_tokens=800)
for entry in result.items:
    # 命中条目按分数排序；每个命中后面跟着它一跳展开的 wiki-link 目标
    print(entry.source, entry.item.name, entry.score)
```

跑完之后磁盘上有什么？两个任何编辑器都能打开的 markdown 文件，加一份一行一条的
[journal](/zh/reference/file-format#journal-jsonl)。整个系统就这些。
