# 宿主集成

wikimem 是库，不是框架：它从不调用 LLM，也没有事件循环。由**宿主**
（你的 Agent）在对话的两个位置把它接进来，契约由 ADR-0001 定死：

| 钩子 | 时机 | 成本 | 失败姿态 |
|---|---|---|---|
| **召回** | 每轮开始前 | 0 次 LLM 调用，同步，有预算 | fail-open：什么都不注入 |
| **记忆** | 每轮结束后 | ≤ 1 次 LLM 调用，异步 | fail-open：本轮不记 |

参考实现是
[XnneHangLab 的 wikimem 插件](https://github.com/XnneHangLab/XnneHangLab/tree/dev/src/lab/plugins/wikimem)
（含配置约 240 行）。下面的模式都是从它提炼的。

## 轮前：召回并注入

```python
async def on_before_turn(self, user_text: str) -> str | None:
    try:
        result = self.index.retrieve(
            user_text, limit=10, budget_tokens=800,
        )
        # 记下这轮浮现了什么 —— 记忆阶段把它们当作候选链接目标
        self.related_names = [f"{r.item.category}:{r.item.name}" for r in result.items]
        if not result.items:
            return None
        return "\n".join(
            f"- [{r.item.category}:{r.item.name}] {r.item.content}"
            for r in result.items
        )
    except Exception:
        return None   # fail-open：记忆系统坏了，不能把对话一起带走
```

值得照抄的几个决定：

- **给每条注入的记忆标上 `category:name` 地址。** 模型看到的是稳定地址，
  可以直接引用；抽取阶段也能对着它们写 `[[category:name]]`，不用瞎猜。
- **预算握在宿主手里。** `budget_tokens` 决定记忆最多占用多少 prompt；
  检索保证不越线，并用 `budget_used` 告诉你实际花了多少。
- **外面再包一层 fail-open。** `retrieve` 本身对可选路径的降级不抛错，
  但宿主侧的 wrapper 还要接住其余一切（路径错误、权限问题）——
  记忆的 bug 至多损失一轮召回，绝不能损失这一轮对话。

## 轮后：后台记忆

钩子必须立刻返回；抽取作为后台任务执行：

```python
async def on_after_turn(self, user_text: str, assistant_text: str) -> None:
    task = asyncio.create_task(self._memorize(user_text, assistant_text))
    self._pending.add(task)                       # 保持强引用
    task.add_done_callback(self._pending.discard)

async def flush(self) -> None:
    """等待所有后台抽取完成 —— 优雅退出与测试时调用。"""
    if self._pending:
        await asyncio.gather(*self._pending, return_exceptions=True)
```

`_memorize` 内部：一次 LLM 调用把这一轮变成零到多个条目，然后就是普通的
`store.add`。LLM 的输出一个字都不信：

- **宽容地解析。** 在响应里找最外层的 `[...]` 再 `json.loads`；
  解不出来 → 本轮不记忆。
- **逐条校验，不是整批。** 分类 slug 非法或名字含保留字符时 `store.add`
  抛 `ValueError` —— 跳过那一条，其余照存。
- **每轮设条数上限**（参考实现用 8），一次话痨式抽取不至于灌爆存储。

## 抽取 prompt

一份 prompt 干两件事 —— 抽事实，*同时*织图。真正值回票价的规则
（全文见参考实现，设计按 lab ADR-0002 借鉴自 memU）：

- **每条自包含** —— 单独读也能懂，与对话相同语言。
- **排除短时效** —— 天气、寒暄、正在进行的任务细节。
- **归属分清楚** —— 用户说的记为用户的事实；助手自己的设定/承诺才记为助手的。
- **`category` 用小写 slug**（给出基础集：`preferences`、`daily_life`、
  `profile`、`event`、`knowledge`、……，允许新建）—— 与 wikimem 的分类校验
  对齐。
- **`name` 简短且稳定**，不含 `: | # [[ ]]` —— 与 `sanitize_item_name` 对齐。
- **能链接就别复述**：把已有分类（`store.categories()`）和本轮召回浮现的
  条目（上文的 `related_names`）作为候选链接目标传进去，新事实与旧条目相关时
  让模型在内容里写 `[[category:name]]`。wiki-link 图就是在这一刻织出来的。
- **空数组是合法答案**：没有值得记的就输出 `[]`。

## 同名条目即更新

`store.add("preferences", "coffee", "...")` 会**替换**已存在的
`preferences:coffee` —— 抽取 LLM 更新一条见过的旧事实，走的就是这条自然路径
（journal 记为 `update` 而非 `add`）。这依赖简短稳定、像名字的条目名；
要是名字里带时间戳或流水号，每次更新都会变成一条重复记忆。

## 部署备忘

- **一个进程，一个 store。** 单个分类文件的写入是原子的，但维持索引新鲜度的
  revision 计数器是进程内状态。多进程同写一个目录不是受支持的拓扑。
- **重启是免费的。** BM25 索引启动时从文件重建；向量缓存（如有）按内容哈希
  增量同步。没有需要保温的状态。
- **盯两个信号**：`embedding_used`（融合路径实际跑了多少）和
  `unresolved_links`（值得修复的悬空链接）。
