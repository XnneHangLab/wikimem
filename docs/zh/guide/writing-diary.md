# 写日记

[日记](/zh/reference/file-format)是**事件层** —— 一条瞬间一段
生动短文，用角色的口吻写。wikimem 只**存**这些条目
（[`Diary.append`](/zh/reference/api)），从不替你写。写什么、怎么写，是你
宿主的 memorize 环节 —— 一次由你掌控的 LLM 调用。

这一环节有**两个自然的时机**，wikimem 两个都支持：

| | 什么时候跑 | 谁写下这条 |
|---|---|---|
| [**后台抽取**](#接线) | 一轮结束之后，不在关键路径上 | **你**发起的那次 LLM 调用，带提示词 |
| [**Agent 工具**](#另一种写法-角色自己动手) | 就在这一轮里，角色决定要记 | Agent 自己，边回话边写 |

本页是前者的**参考提示词**，外加两种接法里最省事的那种。英文版同一份文案已作为
[`wikimem.DIARY_PROMPT`](/zh/reference/api#memorize) 随包提供，默认值因此可复现；你可以
复制、改口吻，或用 `prompt=` 整份替换（下面「换一种语言」）。

## 什么该进日记

只记**发生过的事** —— 有明确时刻的事件。"一直为真"的事实（"在一家机器人公司
上班""不喝咖啡"）是**状态**，状态归 wiki，不进日记。日记的职责是那个被经历的
瞬间，不是那条常驻的事实。

## 参考提示词

```text
你是 {character}（一个陪伴型 AI），在写自己的日记。每轮对话之后，把你想记住的
瞬间写下来 —— 用你记住它的方式。如果这轮没有值得留存的事，就返回一个空数组。
不要编造，只写对话里真实发生的。

每条写成一段短文（2–4 句），用你自己的口吻，把场景、情绪、事实揉在同一口气里
—— 是一段被记住的瞬间，不是一行流水账：

  ✗  "用户跳槽去了一家机器人公司。"
  ✓  "今天下午他说跳槽去了一家做机器人的公司，语气一下子亮了起来——
      能感觉到他憋了好久就想跟我讲这件事。"

规则：
- 一条一个事件，具体、有细节。
- 那一刻若带着情绪，就让它显出来 —— 这正是日记的意义。
- 不要在这里记"一直为真"的事实（那是状态、归 wiki，不是事件）。
- 事件牵涉到的 wiki 条目，可用 [[file:item]] 链接。
- 用用户的语言书写。

本轮对话：
{conversation_turn}

返回一个 JSON 数组。日期和时间由宿主 stamp，你只写正文：
[ { "content": "…那段生动短文… [[links]]" } ]
```

## 接线

`memorize()` 帮你跑这段提示词：一次 LLM 调用，然后解析 + 落盘。**LLM 是你的** ——
wikimem 不构造客户端、不持有 key、不挑 provider。你只实现一个方法，形状就是所有
provider 和网关都认的 `chat_completion`：

```python
from wikimem import MemoryStore, memorize

class MyLLM:                      # 你的客户端、你的模型、你的重试
    def chat(self, messages):
        r = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        return r.choices[0].message.content

store = MemoryStore("memory/")
entries = memorize(
    store.diary, turn_text,
    llm=MyLLM(),
    character="伊蕾娜",            # 会插进提示词
    owner="user:xnne",
)                                 # -> 没什么值得记的就是 []
```

**放到后台跑。** 这里刻意不做 async：`memorize()` 就是一个普通阻塞调用，**何时
跑由宿主决定** —— 一轮结束后丢进 `asyncio.to_thread` / 任务队列 / worker，别挡住
回复。只保留一种同步形状，接口面才不会膨胀；调度、重试、超时都留在你的 `LLM` 里。

### 换一种语言，不需要第二份提示词

`DIARY_PROMPT` 是英文的，但里面写了**"用用户的语言书写"** —— 中文对话自然产出
中文条目。若你想连**指令本身**也用中文（比如上面那份），传一个参数即可：

```python
memorize(store.diary, turn, llm=MyLLM(), prompt=上面那份中文提示词)
```

这正是框架只发一份默认值、而不是维护一张「每语言一份」矩阵的原因：多一种语言，
对你只是多一个字符串，对 wikimem 是零成本。

### 模型答得不好时

`memorize()` 与 embedding 一样 **fail-open**：会剥掉 ``` 代码围栏、接受单个对象；
散文或坏 JSON 一律返回 `[]` 而不是抛异常 —— 一次糟糕的回复不该弄挂你的后台任务。
`[]` 同时也是**正常**结果：大多数轮次本就没什么值得记，提示词要求宁可返回空也不要编。

## 另一种写法：角色自己动手

`memorize()` 是**回头看**：一轮结束之后，从对话里抽。另一种形状是角色**在对话
当中**决定留下点什么 —— "等等，这个我想记住" —— 并且当场说出来。那就是一次
tool call，而这个 tool 由 wikimem 提供：

```python
from wikimem import MemoryStore, diary_tool, handle_diary_tool

store = MemoryStore("memory/")
tools = [diary_tool()]              # 和 Agent 自己的其它工具注册在一起

reply = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools)

for call in reply.choices[0].message.tool_calls or []:
    if call.function.name == "append_diary":
        entry = handle_diary_tool(
            store.diary,
            call.function.arguments,   # 原始 JSON 字符串就行，dict 也接受
            owner="user:xnne",         # 溯源与时间仍然归你
            source_conv=conv_id,
        )
        messages.append({
            "role": "tool", "tool_call_id": call.id,
            "content": f"saved to {entry.date} {entry.time}",
        })
```

**`handle_diary_tool()` 里没有任何 LLM 调用。** Agent 本身就是那个模型 —— 那段
文字是它在回话时自己写的，handler 只做校验与落盘。这就是"在对话中间记一笔"却
不多花一次调用的原因，也是角色说"这条我记下来了"时，那句话是**真的**的原因。

工具的 description 与 `DIARY_PROMPT` 用的是**同一套文风规则**（一条一事件、
2–4 句、只记发生过的事、用用户的语言）—— 一份配方服务两种模式，两边才不会写出
两种口吻。

### 模型写**什么**，你来 stamp **什么时候**

schema 里只有一个参数 `content`。没有 `date`、没有 `time`、没有 `owner`。模型没
有时钟，它给出的日期只能是猜的 —— 而猜错的那条会落在错误的一天，且看上去毫无破
绽。这些一律由你以关键字传给 `handle_diary_tool()`，与 `memorize()` 的分工一致。

### 它**抛异常**，而 `memorize()` fail-open

刻意相反，因为"空"在两边意味着相反的事：

- `memorize()` 返回 `[]` = "这一轮没什么值得记的" —— 正常、健康的结果。
- 一次坏掉的 **tool call** = 角色刚宣布她要把这件事记下来，而它没落地。这里最糟
  的结果恰恰是"悄悄成功"。

所以参数不合法时会抛 `ValueError`，消息本身就是写给 Agent 看的、可以直接当作
tool 结果回传：

```text
diary tool call has unexpected argument(s): date; only 'content' is accepted
(the host stamps time and provenance)
```

Agent 能在同一轮里据此自我纠正。用 `try/except ValueError` 包住，把 `str(exc)`
作为该工具的返回内容即可。

### provider 的 tool 形状不一样时

`diary_tool()` 返回的是 `chat_completion` 的 `tools=[…]` 形状 —— 与 `LLM` 端口
同一个"只认所有人都会说的那一种协议"的选择。若你的不是这种，零件都在：

```python
t = diary_tool()["function"]
anthropic_tool = {
    "name": t["name"],
    "description": t["description"],
    "input_schema": t["parameters"],
}
```

每次调用都返回一个全新的 dict，所以你为自己的 Agent 改个工具名、收紧一下
description，都不会漏到别人那里去。

## 给宿主的注记

- **时间由你来定。** 宿主在调用 [`Diary.append`](/zh/reference/api) 时传入
  `date` / `time` —— 通常就是"现在"。若用户叙述的是**过去**的事（"昨天我们吵架
  了"），请你自己把时间解析出来并显式传入；框架不会从文本里猜。
- **口吻和语言是你的。** 示例是中文，因为陪伴角色是中文的 —— 换成你角色的人设
  与语言即可。wikimem 保持中立：你递给它什么段落，它就存什么。
- **预算。** 如果你的 memorize 环节同时也抽 wiki 状态，把它放进**同一次** LLM
  调用里、拆 JSON 即可 —— 一次调用仍满足"每轮 ≤ 1 次 LLM 调用"（ADR-0001）。
  本页只聚焦日记那一半；wiki 那一半是你抽取提示词自己的事。
