# ADR-0004: 接口契约 — Python API 是契约，CLI 与 serve 都是薄壳

- **状态**：Proposed（2026-07-21，随 PR 评审定稿；CLI 部分为对 [#12](https://github.com/XnneHangLab/wikimem/pull/12) 既成事实的追认）
- **日期**：2026-07-21
- **关联**：[XnneHangLab ADR-0001](https://github.com/XnneHangLab/XnneHangLab/blob/dev/docs/adr/0001-llm-mode-memory.md)（零依赖 CLI 清单来源）、XnneHangLab ADR-0004（宿主消费方式）、`docs/reference/api.md`

## 背景

wikimem 已有两类消费者，将有第三类：

1. **宿主进程内 import**（XnneHangLab 插件）：毫秒级，对比 memu-cli 子进程 2.1–2.4 s/call 的路线（XnneHangLab ADR-0003）。
2. **CLI**（#12 已落地）：`ls / show / grep / explain / graph`，stdlib 实现。
3. **进程外消费者**（将来）：记忆浏览工具、其他应用、宿主之外的前端——需要一个数据接口而不是命令行。yutto 的 serve/RPC 改造是先例：不执著于 CLI，在数据接口上让应用层套自己的壳。

需要明确：谁是契约，谁是壳；传输协议怎么定。

## 决策

### 1. 契约 = Python API

`MemoryStore` / `MemoryIndex` / `Journal`（以及 ADR-0001 落地后的 Diary API）。语义、参数、返回结构以 `docs/reference/api.md` 为准；破坏性变更走语义化版本。

### 2. CLI 与 serve 都是薄壳

同一套 API 外面的两层皮。**壳内不允许业务逻辑**——不在壳里加检索规则、不在壳里分叉融合参数默认值；壳只做参数转换与输出格式化。CLI 已按此形态落地（#12）；serve 照此新增。

### 3. serve：HTTP + JSON，`[serve]` extra

- 端点与 API 方法一一对应，外加 `/version`。
- **不自研协议**：HTTP + JSON + 语义化版本号，够了。
- 依赖归 `[serve]` extra（与 `[embed]` 同一模式），核心零依赖不破；实现期在 stdlib `http.server` 与轻量框架之间取舍。
- 默认绑定 `127.0.0.1`、无鉴权——面向本机进程外消费者；文档言明不要公网裸奔。

### 4. 宿主不走 serve

XnneHangLab 继续进程内 import。serve 面向**进程外**第三方，不是宿主链路的一环——宿主前端的可视化路由由宿主自己的 FastAPI/WebSocket 提供（见 XnneHangLab ADR-0004）。

### 5. UI 永不进框架

框架的责任止于**数据可及**：列日期、读条目、检索、journal tail 都是 API 方法（因而自动是 CLI 子命令和 serve 端点）。界面长什么样是应用的事。file-first 还附赠一条：markdown 真相意味着 Obsidian / 任意编辑器天然是能用的"记忆浏览器"，debug 场景直接够用。

## 理由

- 单一契约消除三类消费者之间的行为漂移——壳里无逻辑，就没有"CLI 结果和 API 结果不一样"这种 bug 类别。
- HTTP + JSON 是所有语言、所有前端的最大公约数；自研协议在这个规模上只有成本没有收益。
- serve 做成 extra 延续了"能力渐进增强、核心零依赖"的既有模式（`[embed]`、`[zh]`）。

## 后果

**正面**

- 应用层套壳有了稳定的地基；换前端、加工具不动框架。
- 三个表面（API / CLI / serve）共享同一套测试对象。

**负面 / 代价**

- serve 的安全面需要文档与默认值兜底（本机绑定、无鉴权的边界说清楚）。
- API 一旦宣布为契约，公开方法的签名变更成本上升——这是目的，也是代价。

**实施**

serve 作为独立里程碑（建议 M6）：端点映射 → `/version` → 文档（reference 增 serve 页）→ 集成测试。
