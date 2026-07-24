# ADR-0005: memorize — 注入式 LLM，两种宿主驱动写入（后台抽取 / Agent 工具）

- **状态**：Proposed（2026-07-24，随 PR 评审定稿）
- **日期**：2026-07-24
- **关联**：[ADR-0001](./0001-diary-store.md)（日记原语，写入对象）、[ADR-0004](./0004-api-contract-thin-shells.md)（契约 = Python API，壳内无业务逻辑）、[XnneHangLab ADR-0001](https://github.com/XnneHangLab/XnneHangLab/blob/dev/docs/adr/0001-llm-mode-memory.md)（硬约束：框架零 LLM、memorize ≤1 次由宿主发起）、[XnneHangLab ADR-0002](https://github.com/XnneHangLab/XnneHangLab/blob/dev/docs/adr/0002-memu-design-not-dependency.md)（借鉴 memU 设计而非引入依赖）、`docs/guide/writing-diary.md`（参考提示词）

## 背景

硬约束 2：**框架本体零 LLM**；memorize 至多 1 次 LLM 调用、由宿主发起。参考提示词（`writing-diary`）已经给出"日记怎么写"，但没规定宿主"怎么调 LLM" —— 而宿主接入时冒出**两种自然形态**，二者都该支持，且都走**注入**（框架不捆绑 provider/keys）：

1. **不想等**：对话不该为写日记阻塞。希望抽取在后台异步跑完，用户无感。
2. **Agent 自己写**：角色在对话里主动说"哇，这个我帮你记下来"，把写日记当成一个 **skill / tool** 来调用，愿意为此花点时间。

mem0 / memU 把 memorize LLM 连同 provider 一起塞进库里。我们不这么做（XnneHangLab ADR-0002 的教训 + 硬约束 1 零基础设施）：宿主本来就有 LLM，框架只提供"配方"（提示词 + schema + 校验 + append），**LLM 实例由宿主注入**。问题是：把这份"配方"以什么形状交给这两种宿主。

## 决策

### 1. 定义一个极小的 LLM 端口（Protocol）

```python
class LLM(Protocol):
    def complete(self, prompt: str) -> str: ...
```

宿主用自己的客户端实现它（同步或异步各出一个 Protocol）。框架**永不捆绑** LLM / provider / keys —— 与 `Embedder` 端口同一套路：能力由注入而来，核心零依赖不破。

### 2. 模式 A — 后台抽取（"别让我等"）

宿主在一轮结束后，把 `memorize(...)` 当**后台异步任务**跑；框架负责编排，一次 LLM 调用、脱离对话关键路径：

```python
def memorize(diary, turn, *, llm: LLM, ...) -> list[DiaryEntry]:
    raw = llm.complete(DIARY_PROMPT.format(turn=turn))  # 参考提示词
    return [diary.append(e["content"], **meta) for e in _parse(raw)]  # 解析 + 落盘
```

这就是 mem0/memU 的便利（"调一个函数，得到记忆"），只是那次 LLM 调用用的是**注入的** `llm`。异步与后台调度归宿主（框架也可另出一个 `amemorize` 便利）。

### 3. 模式 B — Agent 工具 / skill（"我帮你写日记"）

框架提供一个 **tool 定义（function-call schema）+ handler**：

```python
diary_tool()  # -> 一个 function-call schema：append_diary(content: str, ...)
handle_diary_tool(diary, args) -> DiaryEntry   # 把工具调用参数落盘
```

宿主把该 tool 注册进自己的 Agent；当角色在对话中决定记一笔，Agent 调用它，handler 落盘 `diary.append()`。**内容由 Agent 当场自己写**（它就是回路里的 LLM），**没有额外的抽取调用**；同步发生在这一轮内 —— 会花点时间，但那是角色的主动动作，用户看得见。

### 4. 两者都注入、都可选、核心仍零 LLM

- 模式 A / B 都用宿主的 LLM / Agent，**opt-in**；**框架直接发起的 LLM 调用数为零**（注入的 callable 不算，与 embedder 同理），仍满足"≤1 次、由宿主发起"。
- **同一份参考提示词服务两者**：模式 A 把它喂给抽取调用；模式 B 把它的文风规则写进 tool description。
- "写得不如我们想要"的风险由框架侧兜住：**提示词 + JSON schema + 写入校验 + append 都在框架**，宿主只管 LLM 接线。

### 5. 边界（壳内无业务逻辑，ADR-0004）

`memorize()` 与 tool handler 是**编排**（提示词 → 调用 → 解析 → append），不是检索/融合规则。它们不改变 diary/wiki 的语义，只把"注入的 LLM 产出"变成"合规的条目"。写什么、何时写、什么文风仍是宿主策略（ADR-0001）；框架给的是可复现的默认配方。

## 理由

- 两种真实形态：**自动后台记日记**（无感、不打断）vs **角色主动记一笔**（有感、"角色选择了记住这件事"）。陪伴场景两者都要。
- 都走注入 → 零耦合、provider 无关，守住硬约束 2（框架不直接调 LLM）。
- 便利性（mem0/memU 的卖点）拿到了，耦合（provider / keys / 通用文风）没背上。

## 后果

**正面**

- 宿主拿到 mem0/memU 式便利，但无耦合；后台与主动两种记法都支持。
- 核心仍零 LLM / 零依赖（LLM 经端口注入）。
- 一致性（"写得如我们想要"）有了框架侧抓手：提示词 + schema + 校验。

**负面 / 代价**

- 新增可选面：`LLM` 端口、`memorize()` helper、tool 定义 / handler，需维护。
- tool schema 与抽取 JSON schema 成为兼容面，随语义化版本管理。
- 同步与异步端口二选一还是都给，实现期定。

**实施**

- 参考提示词已落地（PR #22）。**Phase 2**：`LLM` 端口 + `memorize()`（模式 A）+ `diary_tool()` / handler（模式 B）+ 测试；`writing-diary` 指南扩写两种模式的接法。全部可选、零依赖核心不破。
