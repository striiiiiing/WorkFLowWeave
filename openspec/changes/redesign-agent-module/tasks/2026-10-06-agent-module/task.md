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
| Agent 前端使用 LangChain Vue 3 | npm `@langchain/vue` 提供 Composition API `useStream`、v2 streaming protocol 和自定义 adapter；当前前端仍自维护 EventSource/composable 状态 | 通过自定义 AgentServerAdapter 对接 LogAgent API；不把后端伪装成官方 hosted Agent Server，不在组件中保留第二套流状态机 |
| Agent/Workflow 共用 storage_primitives | 用户明确要求设计；两边已有 atomic 写、digest、SQLite、JSONL/版本类重复底层需求 | 只共用无业务语义原语；不合并 checkpoint、SessionStore、events、artifact 和 retention |
| 不新增业务 specs | 本 change 不改业务行为；openspec/README.md 的 skip_specs 约定 | 验收引用原规范矩阵；不是跳过行为测试或宣布历史规范已验收 |
| 新建设计和任务 | 用户本轮明确请求重新设计；用户 SDD 约定 | 不修改旧 design/proposal；未来设计变化新建任务记录，不能改历史勾选冒充完成 |

## 2. 默认值与保持理由

下表不是第二份配置定义。运行时仍只读 `src/logagent/agent/config.py:AgentConfig`；此处用于解释为什么此次迁移不顺便调参。

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
rtk proxy uv run ruff check src/logagent/agent src/logagent/storage_primitives tests/agent tests/storage_primitives
rtk proxy uv build --out-dir /tmp/logagent-agent-module-dist
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
