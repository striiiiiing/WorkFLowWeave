# 源码依据与行为验收矩阵

本文件是派生的证据索引，不替代 proposal/design 或原业务规范。读取日期：2026-10-06。源码读取用于判断当前职责，不表示相关行为已经通过运行测试。

## 1. QwenPaw 参考

邻仓 HEAD：`4279e4920f4ccc606fb0805808ef15b5b1d68143`。路径相对其仓库根；LogAgent 文档应可独立评审，不依赖把邻仓复制到本仓。下表列出实际读取的对象与采纳范围。

| 路径 / 对象 | 观察与设计依据 |
| --- | --- |
| `src/qwenpaw/runtime/builder.py:AgentBuilder` | 独立构建模型、提示和 toolkit；采用依赖装配分离，不复制工具 whitelist/skills 功能 |
| `src/qwenpaw/runtime/runtime.py:Runtime.run` | 将 build 和 execute 分开；采用职责分离，不复制八阶段 hooks |
| `src/qwenpaw/runtime/executor.py:AgentExecutor.run` | 框架事件消费与翻译独立；不复制 runtime 层 heartbeat，服从 LogAgent FastAPI SSE 方案 |
| `src/qwenpaw/agents/react_agent.py:QwenPawAgent` | 构造依赖由 builder 注入；保持 LogAgent 使用 LangGraph |
| `src/qwenpaw/agents/context/base.py:ContextManager` | 上下文策略边界明确；不引入第二种压缩机制或自动 overflow 重试 |
| `src/qwenpaw/agents/prompt_builder.py:PromptBuilder` | 提示词装配独立；不采用 provider 异常返回空字符串的处理 |
| `src/qwenpaw/agents/offloader.py:QwenPawOffloader` | 原始输出与活跃上下文分开；其跨 session 日期归档不符合本项目事件日志边界 |
| `src/qwenpaw/app/workspace/workspace.py:Workspace` | 长生命周期资源与每次执行分开；不采纳每 workspace 一套 ChannelManager |
| `src/qwenpaw/app/workspace/service_manager.py:ServiceDescriptor` | cancellable 初始化前应使资源可被清理；应用到现有 lifespan，不新造通用容器 |
| `src/qwenpaw/app/workspace/service_factories.py:create_driver_service` | 先登记已创建资源再 await 初始化，可避免启动中断泄漏 |
| `src/qwenpaw/app/chats/repo/base.py:BaseChatRepository` | 查询/保存责任独立；不复制 chats.json 作为对话正文来源 |

QwenPaw 的 `app/agent_context.py` 存在从请求/配置选 agent 的逻辑，但 LogAgent 当前没有要求多 agent 或 active-agent 默认回退，故不用于新增路由规则。

## 2. LogAgent 证据

| 源文件 | 实际观察 | 对应决定 |
| --- | --- | --- |
| [service.py](../../../src/logagent/agent/service.py) | 1350 行；创建具体依赖、会话、任务、事件流、恢复、配置和绑定文件 | design §1、§3、§6 的拆分 |
| [graph.py](../../../src/logagent/agent/graph.py) | `_langchain_tool` 同时管理调度、started、执行、artifact、completed 和任务表 | tools executor 与框架适配分离 |
| [context.py](../../../src/logagent/agent/context.py) | token 预算、prompt、压缩、命令边界混在同文件 | context 三类职责独立，仍只有一套压缩实现 |
| [events.py](../../../src/logagent/agent/events.py) | JSONL、文件锁、工具预留和可重建索引 | 保留原子事实边界，不因拆 executor 而移动原子预留到内存 |
| [workspace.py](../../../src/logagent/agent/workspace.py) | `_location` 同时负责物理路径和 runtime 逻辑映射 | 分离映射，复用唯一文件边界，不双重校验 |
| [commands.py](../../../src/logagent/agent/commands.py)、[agent/channel.py](../../../src/logagent/agent/channel.py) | AgentChannel 是命令分发；AgentChannelProcessor 实际协调渠道绑定 | 命令分发留 agent，绑定处理归 channel |
| [channel/agent.py](../../../src/logagent/channel/agent.py) | 仅转导 AgentChannel/AgentCommand | 用实际渠道适配器替代转导，不保留长期双路径 |
| [config/registry.py](../../../src/logagent/config/registry.py) | `BUILTIN_TOOLS` 存放五个内置工具路径 | 路径随迁移更新，Service 不再维护第二份默认工具表 |
| [config.py](../../../src/logagent/agent/config.py) | 集中声明预算、超时、并发和沙箱默认值 | 保留默认值来源，任务记录理由 |
| `src/logagent/workflow/graph/*`、`workflow/execution/runner.py` | Workflow 已使用 StateGraph、context_schema、`langgraph.runtime.Runtime`、Send、checkpointer 和 astream_events | Agent runtime 直接采用同一 LangGraph 原生边界，但不共享 graph/state/checkpoint |
| `src/logagent/workflow/storage/*` | Workflow 已有 SessionStore、SessionView、SQLModel facts、retention 和 checkpoint adapter | 只抽取底层 storage primitives；业务存储继续由 Workflow 拥有 |
| `frontend/package.json`、`frontend/src/modules/agents/` | 当前前端自维护 API/EventSource/composables，未使用 LangChain Vue | 引入 `@langchain/vue` `useStream` + 自定义 AgentServerAdapter，组件不再拥有第二套流状态 |
| [交互与存储分析](../../../docs/open-spec-interaction-and-storage.md) | 区分规范/实现，介绍 workspace/runtime/归档/渠道边界 | 阅读入口；需结合后续 MCP 和 FastAPI 方案校正解释 |

## 3. 规范到验证的映射

这些是已有行为的回归目标，不是新增 specs。当前 `openspec/specs` 为空，引用 changes 中的具体规范；实现验收仍需运行测试，不以历史 task 勾选代替。

| ID | 原规范 / Requirement | 本次必须保持的观察结果 | 已有测试位置 / 后续补证 |
| --- | --- | --- | --- |
| A1 | [Agent interface](../archive/add-file-centric-agent/specs/agent-interface/spec.md)：Message submission is idempotent and stream is resumable | 同请求复用 turn，同 session 不并发，重连接续原事件 | `tests/agent/test_admission.py`、`test_service.py`；两个不同渠道竞争同一 session 场景 |
| A2 | 同上；[渠道重设计](../redesign-agent-channel-manager/specs/channel/spec.md) | 断开 waiter 不取消 turn；stop 清理完成才允许下一轮 | `tests/agent/test_task_ownership.py`、`tests/channel/test_platform_admission.py`、`test_unified_queue.py` |
| A3 | [绑定规范](../bind-duplex-channel-conversations/specs/channel/spec.md) | 未绑定不自动创建 session，改绑不能错投旧输出，通知不需要会话绑定 | `tests/channel/test_instance_bindings.py`、`test_channel_manager.py`、`tests/lifecycle/test_agent_channels.py` |
| A4 | [Agent runtime](../archive/add-file-centric-agent/specs/agent-runtime/spec.md)：Checkpoints and side effects are retained safely | interrupted 工具不自动重做，已完成结果复用；fork 不改变父分支 | `tests/agent/test_framework_contracts.py`、`test_service.py`、`test_final_contracts.py`；迁移前数据夹具 |
| A5 | 同上：Memory and history are readable files | AGENTS 下一轮生效；两个 session 读取 self.json 得到各自身份 | `tests/agent/test_turn_config.py`、`test_workspace.py` |
| A6 | 同上：Compaction uses a fixed configurable budget | 自动/手动共用一次摘要，完整消息组，失败保留上下文 | `tests/agent/test_context.py`、`test_framework_contracts.py`、`test_final_contracts.py` |
| A7 | 同上：Reads can run concurrently and writes are exclusive per workspace；Sandbox is simple, explicit, and optional | 共享读槽/写独占；沙箱不可用明确失败 | `tests/agent/test_scheduling.py`、`test_execution.py`、`test_task_ownership.py` |
| A8 | [MCP Agent interface](../redesign-mcp-schema-first/specs/agent-interface/spec.md) | 五入口中的 mcp 固定；schema 完整；原始 MCP 字段保留；未知结果不重放 | `tests/agent/test_mcp_binding.py`、`test_final_contracts.py`；原 MCP 测试继续负责 SDK/schema 行为 |
| A9 | [Workflow handoff](../redesign-mcp-schema-first/specs/workflow-agent-handoff/spec.md)、[Workflow Agent MCP](../remote-workflow-deployment-plugin-compat/specs/workflow-agent-mcp/spec.md) | 保存来源/服务/工具/参数和绑定身份；CLI 不转 MCP，fork/restart 不扩全局范围 | `tests/agent/test_workflow_mcp_binding.py`、`test_mcp_binding.py`；补真实 session 的重启/fork 交接组合测试 |
| A10 | [FastAPI application boundary](../centralize-fastapi-lifecycle-sse/specs/fastapi-application-boundary/spec.md)、[SSE transport](../centralize-fastapi-lifecycle-sse/specs/fastapi-sse-transport/spec.md) | 唯一组合根；原生 SSE 保留 ID/字段；断开释放订阅 | `tests/interaction/test_agent_api.py`、`test_sse.py`、生命周期启动失败用例 |
| A11 | [Agent interface](../archive/add-file-centric-agent/specs/agent-interface/spec.md)：Users can inspect files and actual tool behavior | UI 写文件与工具使用同锁/ETag，禁用工具不注册 | `tests/agent/test_workspace.py`、`test_tool_registry.py`、`test_final_contracts.py`、Agent API 用例 |

新结构另需静态验证：runtime 不导入 transport/具体 integrations；storage_primitives 不导入 agent/workflow/LangGraph；Agent storage adapter 不导入 Workflow storage；Service 不构造具体 manager；Vue 组件不直接创建 Agent EventSource；旧内部导入无遗留。此类测试证明内部边界，不作为新增产品 capability。

## 4. 已识别的实现疑点

以下只记录阅读发现，不据此宣称缺陷已复现或擅自修改业务规范：

- `MCPGateway.execution()` 当前总返回 read；其执行类别应与 MCP runtime 的契约核对，不能借目录迁移添加一套权限判定。
- `_prepare_checkpoint` 为未配对调用补 unknown，需核对已有 completed 事实如何复用；迁移时先补组合场景证据，不能机械复制后宣称恢复契约全通过。
- EventLog 当前对缺换行尾部报错；历史设计允许有明确诊断的尾部隔离。本次不得静默删尾行或改变恢复规则。
- `WorkspaceBackend._location` 支持 `Runtime/` 映射，且关闭沙箱时存在宿主路径能力；不能把“内部文件不作为公共资源”误写为绝对安全隔离已验证。实现阶段核对 API 与模型工具的实际授权边界；不以重构名义新增或削弱权限。
- FastAPI 组合根尚有独立变更，当前 workspace 存在用户未提交的前端和交互层改动。实施前重新检查，不覆盖这些工作。

这些疑点的处置记录放入 task.md：记录原规范、实际测试、是否是已有偏差。设计不变的修复记录执行依据；需要改变契约的部分另建 change。
