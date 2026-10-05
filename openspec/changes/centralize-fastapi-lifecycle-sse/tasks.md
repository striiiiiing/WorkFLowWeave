# 任务与决策依据

依据：[proposal](proposal.md)、[design](design.md)、[FastAPI application boundary 规范](specs/fastapi-application-boundary/spec.md)、[FastAPI SSE transport 规范](specs/fastapi-sse-transport/spec.md)、现有 `src/logagent/lifecycle/` 与 `src/logagent/interaction/` 实现，以及 FastAPI `0.141.1` 中的 `fastapi.sse` 接口。

本 change 只记录方案二的实施任务。方案三“所有模块跨模块依赖都经过 `interaction/api`”不属于本次任务，下一次更新应新建独立 change，不能在本文件中勾选或通过旁路实现提前完成。

## 实施任务

- [ ] 1.1 固定 FastAPI 侧唯一组合根，整理 `interaction/fastapi/` 目录和公共 app factory；删除旧 lifecycle 作为总控制器的调用关系和重复资源入口。
- [ ] 1.2 拆分原 lifecycle：仅将进程级资源所有权、启动顺序、关闭顺序和错误清理接入 lifespan；将请求级访问改为 `Depends`，应用范围实例放入 `app.state`，并保留 workflow run、Agent turn、reload、MCP 调用和 SSE subscription 的操作/会话级生命周期。
- [ ] 1.3 使用 FastAPI 的 dependencies、exception handlers、response models、request disconnect 检测和后台任务改造 interaction 边界，保持现有 HTTP 路径、请求字段、响应业务字段和会话语义。
- [ ] 1.4 将 workflow、channel、agent 事件流替换为 `EventSourceResponse` / `ServerSentEvent`；移除自定义 `StreamingResponse`/SSE 编码和重复 heartbeat。
- [ ] 1.5 验证订阅 finally 清理、客户端断开不取消共享任务、事件 ID、游标、`Last-Event-ID` 和异常传播。
- [ ] 1.6 将 FastAPI 下限提升至 `>=0.135.1`，重新生成 `uv.lock`，并检查环境中 `fastapi.sse` 的导入和运行时行为。
- [ ] 1.7 更新 interaction、lifecycle、SSE 单元测试和最小 HTTP 集成测试；测试比较解析后的 payload，不绑定非 ASCII JSON 的具体字节编码。
- [ ] 1.8 按“定向测试 → Ruff/type 检查 → 受影响包构建 → 最小 HTTP SSE smoke test”的顺序验证，并运行 OpenSpec 严格校验。
- [ ] 1.9 完成 diff 审查，确认没有保留第二套生命周期组合根、重复 SSE 实现或隐式引入 `interaction/api`；记录真实验证结果和未覆盖限制。

## 默认值与决策依据

| 决策/默认 | 理由和依据 |
| --- | --- |
| FastAPI `>=0.135.1` | 当前环境为 `0.141.1`，`fastapi.sse` 已存在；原生 SSE 能力从 0.135 开始，使用 `.1` 作为包含修复版本的项目下限。 |
| 原生 SSE 默认约 15 秒 ping | 采用 FastAPI 原生响应的默认行为，避免维护第二套 heartbeat；只有业务事件需要时才增加明确的进度事件。 |
| lifecycle shutdown/start timeout 不变 | 资源编排被 FastAPI 吸收，但既有进程级资源契约不变；沿用现有实现及其测试依据。 |
| 只有进程级资源进入 lifespan | lifespan 不适合承载请求业务流程、单次订阅和普通 service 调用；这些职责使用 FastAPI dependency、生成器清理和任务协调机制。 |
| `app.state` 保存共享实例 | FastAPI 提供应用范围状态容器；依赖通过它取得唯一实例，避免保留一个巨型 lifecycle 作为第二个服务定位器。 |
| 保留事件字段、ID、游标和 Last-Event-ID 语义 | 用户选择方案二是边界和实现收敛，不是客户端协议重设计；现有前端和调用方继续依赖这些字段。 |
| 领域模块继续构造注入 | 方案三尚未开始；本次只改变 FastAPI/lifecycle/SSE 归属，避免引入第二个依赖抽象和额外迁移面。 |
| 空闲 ping 测试 patch `fastapi.routing._PING_INTERVAL` | `fastapi/routing.py` 在导入时复制该值；只 patch `fastapi.sse._PING_INTERVAL` 不会改变实际 SSE 生成器使用的间隔。 |

## 当前状态

2026-09-30：按用户要求撤回方案二的未提交实现，恢复到 `7dd8c5b` 的 lifecycle/interaction 结构，并保留此前独立的 MCP 与前端改动。实施任务 1.1–1.9 全部恢复为未完成；proposal、design 与规范保留，等待重新实施。

回退依据：审查发现旧控制器状态分散到 RuntimeState、lifespan、operations 与 health，共享服务引用重复，未达到 design 要求的职责收敛。下方实施与验证记录仅保留为已撤回版本的历史，不代表当前实现或验收状态。

### 回退后验证

- 每条后端测试命令使用 `timeout 60s`。合并回归触及超时，随后拆组取得完整结果：`tests/interaction` 64 passed；`tests/lifecycle` 37 passed；provider、starter resources、resource store、MCP 与 MCP import 共 43 passed、1 failed。
- 唯一失败为 `tests/test_starter_resources.py::test_starter_resources_are_selectable_and_deleted_defaults_stay_deleted`：旧断言期待 mock/logs/history 采集器和 plugin 工具，但当前注册表提供 mcp 工具，默认资源也不再提供旧采集源。该测试、注册表和默认资源与 `7dd8c5b` 一致；此次回退未修订这个已有不一致。
- `uv run --no-sync ruff check src tests`、`git diff --check`、`openspec validate centralize-fastapi-lifecycle-sse --strict` 通过。
- `timeout 60s uv build --wheel` 通过。完整 `uv build` 在 sdist 阶段长时间未完成，已中止，不计为通过。
- 使用真实 ApplicationLifecycle 与 TestClient 的最小 HTTP 启动、健康查询、资源查询和关闭烟测通过。
- 本次回退验证不代表方案二实施完成；任务 1.1–1.9 继续保持未完成。

## 已撤回版本的历史记录

### 2026-09-30 原实施决策（已撤回）

- 根因与分类：原 `ApplicationLifecycle` 同时拥有资源图、请求管理操作和健康准入，interaction 自行维护 SSE 编码和心跳；按 design §1–3 进行结构拆分，不以移动原类或增加兼容控制器完成迁移。
- 实施边界：HTTP 模块及装配辅助模块归入 `interaction/fastapi/`；app factory 配置应用，lifespan 负责进程资源，独立的管理操作协调 reload，dependencies 从 `app.state` 读取服务。CLI 读取配置后使用同一 app factory；HTTP 离线测试通过 `dependency_overrides` 注入服务，不再注入旧 lifecycle 替身。
- 保留现有工作区的 MCP 导入、模型发现错误、MCP 健康监控等未提交实现；迁移资源图时同时保留 `MCPHealthMonitor` 的启动、刷新和停止关系（design §2.1 已列出该资源）。
- FastAPI `0.141.1` 的 `EventSourceResponse` 只是路由标记，编码、ping 与流清理由 routing 层处理。因此 SSE 路由必须声明原生响应并成为异步生成器，不能直接以该类包装领域事件迭代器。依据环境中 `fastapi/sse.py` 与 `fastapi/routing.py` 的实现。
- 生命周期拆分后的职责由 `state.py`（配置、所有权和协调状态）、`lifespan.py`（启动/关闭与清理顺序）、`operations.py`（reload 操作）和 `health.py`（只读探测与准入判定）分别承担；`RuntimeState` 是 app.state 的内部所有权记录，不是第二个组合根。
- 验证依序执行定向单测、Ruff、包构建、真实 HTTP SSE 烟测和 OpenSpec 严格校验；每条后端测试命令使用 60 秒硬超时。下方仅记录实际完成的结果。

### 2026-09-30 原验证结果（不作为当前验收依据）

- `timeout 60s uv run --no-sync pytest -q tests/interaction tests/lifecycle tests/test_provider_creation.py`：109 passed，1 条 Starlette deprecation warning。
- `uv run --no-sync ruff check src tests`：通过。
- `uv build`：成功生成 `dist/logagent-0.1.0-py3-none-any.whl`。
- `openspec validate centralize-fastapi-lifecycle-sse --strict`：通过。
- `PYTHONPATH=. uv run --no-sync python /tmp/logagent-lifecycle-sse-smoke.py`：真实 TCP HTTP smoke 通过；workflow completed、agent events、channel `Last-Event-ID` replay 与空游标恢复均通过。
- `tests/interaction/test_application_boundary.py`、SSE completed-session replay、启动失败清理和原生响应头测试均包含在上述回归中；未覆盖完整浏览器端到端流程。
