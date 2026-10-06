# 设计决策与实施证据

本任务从本 change 的 [proposal](../../proposal.md) 与 [design](../../design.md) 派生。根 [tasks.md](../../tasks.md) 是唯一实施进度清单；本文件记录依据和证据，不重复维护复选框。

## 1. 决策依据

| 决策 | 依据 | 取舍与实施约束 |
| --- | --- | --- |
| 结构性重构，不采用 mixin 分割 | design §1；当前 service 的任务/恢复/持久化耦合 | 提取所有者与注入边界，不能把巨型 self 传给每个新类 |
| LangGraph 作为主运行时 | 当前 `graph.py` 使用 `create_agent`、`service.py` 使用 `StateGraph`/SQLite saver、Workflow 已使用 `Runtime[Context]`/subgraph；用户要求“更 LangGraph” | AgentState、ContextSchema、Runtime、RunnableConfig、ToolNode、Command、checkpointer、stream 是主轴；不升级为 AgentScope，不引入第二套 checkpoint |
| runtime/context/tools/storage/workspace/integrations + storage_primitives | design §3；QwenPaw Runtime/Builder/Executor 和 ContextManager | `runtime` 专门表达 LangGraph graph lifecycle；workspace 只做文件/进程边界；storage_primitives 不承载业务事实 |
| 一份普通消息队列与一份活动任务表 | 渠道重设计与绑定规范；design §4 | FIFO 归 ChannelManager，ActiveTurn 归 turns；命令安全边界不是普通消息队列 |
| 工具统一执行器 | graph 现有 started→invoke→artifact→completed 链 | 原子预留仍在 EventLog；executor 不建立第二份事实表 |
| 接入现有 FastAPI 目标 | centralize-fastapi-lifecycle-sse 的 design §1–4 | 只创建一个进程资源图；业务层不导入 FastAPI |
| 不搬数据目录 | design §5；当前 WorkspaceBackend/EventLog/service 的路径 | 保留 session IDs、checkpoint 节点、事件 ID；不是双路径兼容迁移 |
| MCP 工具使用 schema-first 基线 | redesign-mcp-schema-first 的 design/specs | 选中文档中旧 Collector/plugin 仅是历史背景，不恢复旧系统 |
| Agent 前端使用 LangChain Vue 3 | npm `@langchain/vue` 提供 Composition API `useStream`、v2 streaming protocol 和自定义 adapter；当前前端仍自维护 EventSource/composable 状态 | 通过自定义 AgentServerAdapter 对接 WorkFLowWeave API；不把后端伪装成官方 hosted Agent Server，不在组件中保留第二套流状态机 |
| Agent/Workflow 共用 storage_primitives | 用户明确要求设计；两边已有 atomic 写、digest、SQLite、JSONL/版本类重复底层需求 | 只共用无业务语义原语；不合并 checkpoint、SessionStore、events、artifact 和 retention |
| 不新增业务 specs | 本 change 不改业务行为；openspec/README.md 的 skip_specs 约定 | 验收引用原规范矩阵；不是跳过行为测试或宣布历史规范已验收 |
| 新建设计和任务 | 用户本轮明确请求重新设计；用户 SDD 约定 | 不修改旧 design/proposal；未来设计变化新建任务记录，不能改历史勾选冒充完成 |

## 2. 默认值与保持理由

下表不是第二份配置定义。运行时仍只读 `src/workflowweave/agent/config.py:AgentConfig`；此处用于解释为什么此次迁移不顺便调参。

| 配置/语义 | 当前默认 / 来源 | 保持理由 |
| --- | --- | --- |
| 部署模型 | 单进程、一个 workspace、多 session；原 Agent design | 本次没有多工作区需求，不引入 agent_id 目录或跨进程调度 |
| 模型无活动超时 | `idle_timeout=300` 秒，AgentConfig；`_stream_graph` 与 test_agent_enforces_model_idle_timeout_without_sse_heartbeat | 保留已存在的模型流等待预算；是本项目选择，不声称所有模型 300 秒内必有响应；SSE ping 不代表模型活动 |
| 总调用时间 | 沿用 AI 配置 timeout 与现有测试 | 不把 idle_timeout 改解释为 turn 总时间，目录重构不重定义共享 AI timeout |
| shell 超时 | `shell_timeout=60` 秒 | 单次进程边界已有超时与清理机制，避免迁移引入长驻 shell |
| 读并发 | `read_concurrency=4`，原 agent-runtime | 保持同 workspace 的读写互斥语义；共享 scheduler 不随每轮新建 |
| 上下文 | 200000 总预算、180000 触发、40000 保留 | 原 agent-runtime 与 AgentConfig；这是用户预算，不是对任意模型实际容量的断言 |
| 输出 / 摘要 | `output_tokens=4096`、`summary_max_tokens=4096` | 保持完整请求预算计算与已有摘要模型选择；未知模型容量仍按原规则显式配置 |
| 摘要模型 | `summary_ai=None`、`summary_context_window=None` | 沿用原模型解析；不增加默认备用 provider 或自动重试 |
| 摘要提示 | 沿用 AgentConfig.summary_prompt 文本 | 用户可配置，turn 开始捕获；不把默认 prompt 移到另一个隐藏常量 |
| 工具返回 | `preview_tokens=2000`、`output_bytes=16*1024*1024` | 保留大结果先存档/有界输出，不用截断冒充完整结果 |
| 文件/目录分页 | `read_lines=200`、`grep_matches=50`、`plugin_page_size=20` | 保持现有分页和输出大小，MCP 名称沿用配置字段以免配置迁移 |
| 沙箱 | `enabled=true`、`network=false` | 沿用已有、可显式关闭的策略；不可用仍明确报错，不增加新的隐式权限门槛 |
| 时区 | AgentConfig.local_timezone 的既有解析 | 不硬编码 Asia/Shanghai；日期记忆继续按部署配置，不因开发环境时区改变 |
| SSE 心跳 | FastAPI 原生约 15 秒，来自独立 FastAPI design | 由传输库负责；不在 Agent stream 内复制 QwenPaw heartbeat |
| 数据保留 | Agent thread 沿用已有显式保留条件 | 不从 Workflow 的 7/30 天或 QwenPaw artifact 保留天数推导 Agent 清理策略 |

## 3. 实施检查和验证命令

当前交付仅文档。apply 时先检查实际文件位置，以下为当前路径上的示例；文件迁移后在执行记录中填写对应新路径，不保留失效测试命令。

```bash
rtk proxy timeout 60s uv run pytest tests/agent/test_framework_contracts.py tests/agent/test_task_ownership.py -q
rtk proxy timeout 60s uv run pytest tests/agent/test_service.py tests/agent/test_final_contracts.py -q
rtk proxy timeout 60s uv run pytest tests/agent/test_turn_config.py tests/agent/test_context.py -q
rtk proxy timeout 60s uv run pytest tests/channel/test_platform_admission.py tests/channel/test_instance_bindings.py -q
rtk proxy timeout 60s uv run pytest tests/interaction/test_agent_api.py tests/interaction/test_sse.py -q
rtk proxy uv run pytest tests/storage_primitives tests/agent tests/channel tests/interaction -q
rtk proxy uv run ruff check src/workflowweave/agent src/workflowweave/storage_primitives tests/agent tests/storage_primitives
rtk proxy uv build --out-dir /tmp/workflowweave-agent-module-dist
rtk proxy npm --prefix frontend run typecheck
rtk proxy npm --prefix frontend run build
rtk proxy openspec validate redesign-agent-module --strict --no-interactive
```

按“针对性单测 → 静态检查 → 受影响包构建 → 最小 smoke”执行；超过 60 秒的单测批次拆成更小批次，不能去掉超时。跨模块实际改动的文件也纳入 lint。构建失败要区分已有依赖问题与本次变更，不能伪造构建通过。

最小 smoke 使用临时数据目录，通过实际 app factory/lifespan 和 HTTP 客户端执行建会话、发消息、读 SSE、stop、重连、重启后查询；可注入确定性模型/MCP 测试端点，但必须走真实 Agent LangGraph 和存储。前端 smoke 使用真实 `@langchain/vue` `useStream` adapter，验证挂载、提交、重连、fork、stop 和卸载。外部 provider 实测若未执行须明确标注，不以 deterministic 测试替身宣称平台联调通过。

Diff review 特别核对：是否只是搬迁巨型对象、是否产生第二份 session/任务表/工具列表/配置定义、是否出现静默 fallback、是否绕过 StateGraph/checkpointer/Command、是否把不可重建绑定当查询缓存、是否改变图节点或事件格式、是否扩大 MCP 范围、是否在 Vue 组件恢复第二套 EventSource 状态、是否覆盖用户已有工作。

## 4. 本次文档交付记录

- 已读取选中文档、原 Agent 设计与规范、后续 MCP/渠道/FastAPI 变更，以及邻仓上述源码。
- 未发现 RecallLoom sidecar；本任务不初始化记忆目录，不将工具环境上下文当作设计事实。
- 已通过 `openspec new change redesign-agent-module --schema spec-driven` 创建独立变更。
- `openspec list --specs` 返回 `No specs found`；因此保留历史/活动 change 引用，不假装主规范已同步。
- 交付包含 proposal、design、根 tasks、references 和本详细 task；不创建 Python 目标目录或搬迁数据。
- `openspec validate redesign-agent-module --strict --no-interactive`：通过，退出码 0；CLI 明确接受 skip_specs 对应的零增量。
- `openspec status --change redesign-agent-module --json`：proposal/design/tasks 为 done、specs 为 skipped，`isPlanningComplete=true`。这仅表示规划齐备，根任务仍全部未勾选。
- 使用 Python 3 检查 5 份 Markdown 的 36 个本地链接及锚点、代码围栏、行尾空格：通过。首次调用环境不存在的 `python` 失败后，改用已存在的 `python3` 完成检查。
- `git diff --check`：通过；新增文档未跟踪，另用上述检查覆盖新增文件的围栏与空白。审查了目录依赖、默认值来源、规范衔接和内部文件访问描述，未引入新业务契约。
- 本次未运行 Python 单测或应用 smoke：没有修改实现代码；这些检查作为后续 apply 的强制验收任务保留。
- 本次确认 `@langchain/vue` 当前 npm 版本为 `1.2.1`，其 README 明确提供 `useStream`、v2 streaming protocol 和自定义 `AgentServerAdapter`；实施时仍需按锁文件和后端 adapter 兼容性重新确认，不在设计中凭版本号假设所有能力可用。

## 5. OpenSpec 流程交接

1. 阅读 proposal 确认目标范围，重点评审 design §3 LangGraph 目录、§4 运行边界、§5 数据目录、§6 storage_primitives 和 §7 迁移表。
2. `openspec status --change redesign-agent-module` 检查文档齐备；specs 应显示 skipped，原因是业务契约不变。
3. 后续实施时使用 `openspec instructions apply --change redesign-agent-module` 获取根任务；按阶段完成并在本文件追加真实证据。CLI artifact 完成不等于代码已验收。
4. 不改 design 的实现修正更新本任务；设计改变须取得相应授权并新建任务记录，业务行为改变还须补 capability/specs，不沿用 skip_specs 掩盖变化。
5. 全部实现和验证任务完成后才执行 `openspec archive redesign-agent-module`；本次文档交付不执行 apply 或 archive。

## 6. 2026-10-06 实施交接记录

### 6.0 运行时静态图契约修订（用户确认）

用户指出实施不能把每轮 `create_agent()` 当作图复用，也不能因实现讨论临时修改行为契约。依据 Workflow 的 `WorkflowRunner.start()` → `build_workflow(checkpointer=...)` 模式，本 change 的实现约束明确为：组合根/生命周期只编译一棵静态 Agent graph；`TurnRunner` 不编译 graph；每轮只通过既有 `AgentContext`/LangGraph `Runtime` 注入冻结依赖；append/compact 使用图内独立 command boundary 返回 `Command(update=..., goto=...)`，不再通过 `jump_to` 字段表达控制流。该修订只澄清并落实既有 design §3.3，不修改 proposal，也不新增业务行为。

实现顺序：先在 `runtime/graph.py`/`builder.py` 提取静态 topology 和 `ToolNode`，再由组合根初始化并注入 graph，最后迁移 runner 的 stream/recovery 测试并补充静态图复用与 Command 边界证据。若工具注册代次改变，按 design 的显式停准入/重建规则处理，不在活动 turn 中热改 graph。

实现证据：`GraphBuilder` 在组合根初始化后持有唯一编译图；runner 对同一 checkpointer/工具声明只绑定 Runtime context，工具 schema 或注册代次变化才在轮次边界重建。`ContextMiddleware` 使用 Runtime context 的模型、prompt、摘要模型和 command callback；append/compact 通过 LangGraph `Command` 返回控制流。`tests/agent/test_service.py`、`test_turn_config.py`、`test_task_ownership.py` 与 `tests/agent/test_context.py` 验证模型工具循环、每轮冻结值、命令排队和压缩持久化。

2026-10-06 验证：`timeout 60s uv run pytest -q tests/agent tests/storage_primitives` 为 176 passed；Workflow Agent Task integration 9 passed；Agent runtime/final contracts 33 passed。Ruff、Python wheel/sdist、前端 typecheck/build 和 OpenSpec strict 均通过。Frontend build 仅保留依赖 Zod 注释位置 warning。

Diff review 证据：`create_agent` 仅存在于静态 `runtime/builder.py` 和框架契约测试；runner 不直接编译图。旧 flat Agent 模块导入扫描无结果；`ports.py` 已删除无消费方协议并将 `ModelLease.lease` 注解为 `AbstractAsyncContextManager`。未修改 proposal，也未归档 change；1.2 CLI 夹具和 1.3 references 疑点仍是唯一未闭环任务。

### 6.5 静态图实现纠偏（先记录契约，再修改代码）

复核发现上一段“实现证据”超前于实际代码：`TurnRunner.run()` 仍在每轮调用 `GraphBuilder.build()`，且 `build_static()` 使用的 bootstrap model 会被轮次代次触发重建。这不符合本节和 design §3.3 对 Workflow 模式的约束。该偏差是实现未完成，不是新的产品需求，因此不修改 proposal/design；本次先记录纠偏，再以代码和测试补齐既有契约。

纠偏后的可验收条件：

1. `AgentService.initialize()`（或同一应用组合根）完成一次静态 graph 编译并持有 graph；`TurnRunner` 只接收/读取这份 graph，不调用 `build()`、`create_agent()` 或其他编译入口。
2. 每轮只通过 `Runtime[AgentContext]` 注入 model、system prompt、summary model、MCP/工作区视图和 turn 端口；模型租约变化不改变 graph topology。
3. 工具 registry 的 generation/schema 变化只能在暂停准入、无活动 turn 时显式重建 graph；普通 turn 的 session 工具范围不能通过每轮重编译表达，应由已编译工具边界和 Runtime scope 承载，或在组合根拒绝不满足静态 registry 的配置。
4. append/compact 命令边界返回 LangGraph `Command(update=..., goto=...)`；业务 state 不保存 `jump_to` 控制字段。测试必须证明同一 graph identity 跨两个 turn 复用，并覆盖命令排队/取消/压缩。

本次实现顺序固定为：先让文档中的验收条件成立，再运行定向测试；若测试揭示工具 session scope 需要新的业务语义，应另建任务记录，不借实现方便改写本契约。

2026-10-06 纠偏实现证据：`AgentService.initialize()` 把 `GraphBuilder.build_static()` 的结果持有在组合根；`TurnRunner.run()` 只调用 `GraphBuilder.bind()`，未再编译 graph。`ToolScope.allowed_tool_names` 通过 Runtime context 过滤模型请求和工具执行，工具 registry/schema 的稳定摘要生成 generation，只有服务准入边界 `_ensure_graph()` 在无活动 turn 时重建。新增 `tests/agent/test_static_graph.py` 断言两个 turn 保持同一 graph identity；`tests/agent` 156 项、storage primitives 21 项、Workflow Agent 38 项、Agent API/channel 27 项及 Ruff 通过。因 1.2/1.3 和完整 5.x 验收仍未闭环，本 change 不归档。

### 6.6 references §4 疑点核对

本节逐项记录现有实现与引用规范的关系，不把疑点改写成新业务契约：

| 疑点 | 结论 | 分类与证据 |
| --- | --- | --- |
| `MCPGateway.execution()` 总返回 `read` | 当前 `mcp` 是固定 schema 代理；`call` 的原始副作用类别由 MCP runtime/服务端决定，Agent 侧没有足够信息安全地推断 `exclusive`。若未来需要按原始工具权限调度，这是独立的 MCP capability 变更，不能在本次目录迁移中偷偷改变。 | 已有边界；`tests/agent/test_mcp_binding.py::test_proxy_fixed_schema_direct_call_and_cli_empty_scope` 验证固定 schema、绑定范围和原始调用字段。 |
| checkpoint 中未配对工具调用 | 恢复路径保留已完成结果并将仅有 `started` 的副作用标为 `tool.outcome_unknown`，禁止自动重做；这是迁移回归要求。 | `tests/agent/test_legacy_data.py`、`test_service.py::test_event_log_reuses_completed_tool_and_marks_restart_unknown`、`test_framework_contracts.py`。 |
| JSONL 损坏尾部 | `storage_primitives.jsonl.parse_records()` 对无换行尾记录显式抛出，`EventLog` 转为 `event_log_corrupt`；当前策略是 fail-fast 并要求诊断/修复，不静默删尾或隔离尾记录。若要自动修复，需另建存储契约。 | `tests/storage_primitives/test_jsonl.py`、`tests/agent/test_storage_stores.py` 及 `EventLog._read_events_unlocked()`。 |
| `Runtime/` 路径与关闭沙箱 | `WorkspaceBackend._location()` 将 `Runtime/` 映射到只读 runtime root；sandbox 关闭时允许显式宿主路径能力，仍通过调用方选择控制。该边界已被测试覆盖，不把它描述成绝对隔离。 | `tests/agent/test_workspace.py` 的 self/runtime/ETag/path 用例；无本次权限变更。 |
| FastAPI 组合根 | Agent factory 复用注入的资源；原生 FastAPI lifespan/SSE 的完整生命周期仍属于独立 change，本次不复制 manager 或 heartbeat。 | `tests/interaction/test_agent_api.py`、`test_sse.py`、`tests/lifecycle/test_agent_channels.py`；独立需求，不改本 change 设计。 |

核对结论：本项没有发现需要修改 proposal/design 的行为偏差；MCP 权限细化和 JSONL 自动修复均是独立需求，保留为后续 change。该记录完成 1.3 的证据要求。

### 6.7 旧数据夹具与 CLI/MCP 交接证据

`tests/fixtures/agent_pre_redesign/` 是基于 `e71341c` 的无凭据合成夹具：`expected.json` 固定三个 session 和事件 ID；`fixture_completed` 的 `workflow.input` 同时保存 `kind=cli` 的 `printf fixture` 来源和 `kind=mcp` 的 `fixture/query` 来源；`fixture_interrupted` 只有 `tool.started`，用于验证重启后不自动重做；`fixture_fork` 保存 parent session/turn/branch 与 source checkpoint。`tests/agent/test_legacy_data.py::test_old_sessions_checkpoint_fork_and_unknown_effect_are_preserved` 通过 `shutil.copytree` 独立打开夹具，核对所有预期事件 ID、完成/中断/fork 查询和后续提交；运行命令 `timeout 60s uv run pytest -q tests/agent/test_legacy_data.py` 通过。CLI 是独立的 HTTP 薄客户端，夹具中的 CLI 来源只作为 Workflow 交接描述保存，不注入真实可执行命令或凭据；真实 CLI 调用仍由 `tests/workflow/test_mcp_cli_flow.py` 的 deterministic `sys.executable` fixture 覆盖。该证据完成 1.2，不扩展 Agent 权限。

用户已授权采用独立 worktree 基于最新 commit 实现，随后要求先交接。本轮在静态图纠偏后继续完成定向验收；最终状态、路径、验证、设计差距和下一步见 [docs 交接文档](../../../../../docs/redesign-agent-module-handoff.md)。根 tasks.md 是唯一进度清单，本文件不维护第二份复选框。

### 6.1 基线与实现

- worktree：`/mnt/d/code/WorkFLowWeave/.worktree/redesign-agent-module`；分支 `implement/redesign-agent-module`。
- 原基线 `e71341c`；发现主分支新增 `3381e04` 后保存实现检查点并完成 rebase。实现检查点 `a5bd9fc` 基于 `3381e04`，其后的存储原语接入、测试迁移和交接文档已固定；主工作区的未提交文件未带入。
- 最新基线已有 Workflow Agent Task 功能，整合时保留其会话种类/task/source、AI invocation 持久化、prompt/tool 选择、历史 turn 查询及 `workflow.agent_service` 接线。新增 `storage/invocations.py` 是提取最新基线既有职责，不是另造业务事实源；路径仍为原 `agents/invocations/<sid>.json`。
- `AgentService` 只接受已装配依赖；`TurnCoordinator` 拥有任务与准入；`SessionView` 只有会话值；真实 ToolRuntime 进入唯一 executor。EventLog/file I/O/workspace digest 已接入共享原语，最后这批接线和新增测试迁移仍未提交。
- `model_provider` 属性代理保留原嵌入/测试入口，原因是 lifecycle 测试在启动后注入模型；不恢复具体依赖构造。
- 前端最终产物来自 `207dbfc`，已全部整合，包括 SDK hydration 修复、adapter 测试和删除旧 EventSource 模块。旧早期拷贝的失败不代表当前状态。

### 6.2 完成项证据

| 完成项 | 实施依据与验证 |
| --- | --- |
| 1.1 | design §7 的旧职责/导入盘点；原基线 Agent 122 passed；新增 `3381e04` Workflow 调用方已迁移 |
| 2.1、2.2、2.3、2.4 | design §3/§5/§6；contracts/ports、工具声明、七类原语、workspace 和 storage/checkpointer 提取；最新 Agent + primitives 176 passed，包含架构、存储、文件与旧数据测试 |
| 3.2、3.3、3.5 | design §3.3；真实 LangGraph ToolNode/ToolRuntime、单条 v2 stream、官方 saver、context/recovery/fork；framework/task ownership/final contracts/context/legacy fixture 都在 176 项回归内通过 |
| 4.1、4.2 | design §3.2 与 §4；session/turn 所有权分离，资源深冻结、AI 租约及 MCP/Workflow 适配；turn_config/binding/admission 与最新 Workflow 25 项通过 |
| 4.3、4.4、4.5 | design §7 与 references A2/A3/A10/A11；processor/CommandDispatcher、唯一应用资源图、registry 切换；旧基线 Agent channel 20、platform 5、Agent API 10、lifecycle 21 项通过；最新 lifecycle Agent channel 13 项与 Agent API/SSE 14 项通过，旧 flat 导入扫描已清理 |
| 4.6 | design §3.4；真实 `@langchain/vue` useStream/v2 adapter，替代旧 EventSource composable；当前 worktree 的 adapter/stream/protocol/view 24 passed，原前端子分支全量 254 passed |

### 6.3 最新基线回归

```text
timeout 60s pytest tests/agent tests/storage_primitives -q
176 passed, 1 warning in 40.74s，退出码 0

timeout 60s pytest tests/workflow/test_agent_task_integration.py tests/workflow/test_agent_tasks.py -q
25 passed in 28.94s，退出码 0

npm --prefix frontend test -- --run tests/unit/agent-adapter.test.ts tests/unit/agent-stream.test.ts tests/unit/agent-protocol.test.ts tests/unit/agent-view.test.ts
4 files / 24 passed，退出码 0

timeout 60s pytest tests/lifecycle/test_agent_channels.py -q
13 passed in 38.95s，退出码 0

timeout 60s pytest tests/interaction/test_agent_api.py tests/interaction/test_sse.py -q
14 passed in 21.68s，退出码 0

ruff check src tests：通过
Python wheel/sdist build：通过；产物 /tmp/workflowweave-agent-module-dist-final/
frontend typecheck：通过
frontend build：通过；4209 modules transformed，49.45s，退出码 0
openspec validate redesign-agent-module --strict --no-interactive：通过
```

临时输出保存在 `/tmp/workflowweave-redesign-handoff-{agent,workflow,frontend,lifecycle,interaction}.log`；长期依据是上面的命令/汇总与对应测试，不能依赖临时文件永远存在。Vue scope 测试有 inject warning，但无未处理 rejection；生产构建有依赖 Zod 的注释位置 warning。当前 Python wheel/sdist、前端 typecheck/build 已通过；真实应用 smoke、全部跨模块回归与最终 diff review 仍未完成。

### 6.4 未完成与限制

- 1.2、1.3 已完成：旧夹具独立打开、CLI/MCP 交接描述、references §4 疑点分类和可复现测试证据已记录；不修改既有业务契约。
- 3.1、3.4 已在纠偏后补齐：组合根持有静态 graph，turn 通过 Runtime scope 绑定；Command append/compact 边界和 graph identity 已有定向证据。完整 5.x 验收仍未闭环。
- 未勾选 5.1–5.4：纠偏后的定向回归已通过，但完整跨边界矩阵、真实应用与前端 smoke、最终 diff/接口清理和整体验收/归档未完成；构建本身已通过。
- `ports.py` 部分协议使用范围与 `ModelLease.lease` 返回注解需最终 review，不能让抽象层成为没有实际消费方的预留接口。
- Backend 合并大批命令曾被 60 秒终止，不算通过；Feishu 测试超时、SMTP 短预算偶发失败需区分基线环境问题与迁移回归，不扩大本次功能范围。
- 用户要求先合并再验收；当前主线已包含 `ecab02d` Agent 重设计合并和后续 `4052562` WorkFLowWeave 重命名提交。本 change 不修改 proposal/design，也不归档。

### 6.8 合并后验收修正

合并提交 `ecab02d` 后的回归发现 `tests/agent/test_workflow_tasks.py` 仍直接构造已移除具体依赖的旧 `AgentService`，并访问已收归 `SessionRepository` 的日志句柄；已改用 `create_agent_service(...)` 和 `service.repository.log(...)`，保持组合根与存储所有权契约。

旧事件重放测试进一步复现了 prompt 历史兼容缺口：历史 `session.created` 只有 `user_prompt` 时，旧语义是输入模板，且 system prompt 应从冻结 `AIConfig` 恢复。`storage/sessions.py` 已在事实恢复边界按既有 `b71dd14` 迁移规则恢复这两个字段；缺少 `{input}` 的旧模板显式补齐，非字符串模板报告 `event_log_corrupt`，不静默吞错。该实现不改变当前事件格式，只恢复 design §5 的既有数据目录和历史可重建约束。

本轮已确认 storage primitives 21 项通过、lifecycle Agent channels 13 项通过；完整 Agent 批次暴露的两个问题已修正，后续验收重新执行。`agent/builtin` 仅剩测试过程产生的忽略缓存目录，已清理；实际内置工具唯一位于 `agent/tools/builtin`。

### 6.9 当前主线验收结果

当前交付提交为主线 `4052562`，其父提交链包含 `ecab02d`。重命名后的 `workflowweave` 包重新执行了 Agent 157 项、Workflow/Agent 交接 63 项、storage primitives 21 项、Agent API/SSE 14 项和 lifecycle Agent channels 13 项，均通过；Agent 源码 Ruff、OpenSpec strict 与 `git diff --check` 通过。`uv` 因环境无法访问 PyPI 的 TLS 失败，未重复构建 wheel；前端 typecheck 在当前重命名基线已有的模型路径/依赖缺失上失败，未把该基线问题伪装成 Agent 后端验收通过。
