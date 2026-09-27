## ADDED Requirements

### Requirement: Agent continues a Workflow result and calls collectors once

系统 SHALL 提供基于 LangGraph 1.x 的独立 Agent 会话。用户从 Workflow 历史选择结果时，系统 MUST 将最终输出对象作为 `{input}` 放入新会话上下文，并绑定来源 Workflow session ID；新的 Workflow 运行 MUST NOT 改变已有 Agent 上下文。每次 Collector call MUST 只执行一次并保留真实状态。

#### Scenario: Continue a selected Workflow result

- **WHEN** 用户从 Workflow 历史选择一次完成运行并选择模型
- **THEN** 系统创建绑定该 Workflow session 的 Agent 会话，将最终输出对象插入上下文，并使用所选模型继续对话

#### Scenario: Read Schema and collect once

- **WHEN** Agent 查询启用 Collector 的 Schema 并提交合法调用参数
- **THEN** 系统从本轮资源快照合并实例固定值和调用层参数，调用 CollectorManager 一次并返回原业务状态

#### Scenario: Reject instance overrides

- **WHEN** 调用参数覆盖凭据、连接或其他实例层字段
- **THEN** 系统返回字段错误且不执行 Collector

### Requirement: Tools remain a compact, configurable plugin surface

系统 SHALL 通过统一 PluginRegistry 发布默认 `plugin`、`read`、`write`、`grep`、`shell` 五个工具。Collector 数量增加 MUST NOT 增加顶层模型工具数量；Channel 由绑定的双向路由处理，不暴露任意发送工具。关闭的工具插件 MUST 不导入、不注册且不进入 tools 数组。

#### Scenario: Discover a new Collector

- **WHEN** 新增启用的 Collector 实例
- **THEN** Agent 通过 `plugin.list/schema/call` 发现并调用，顶层工具定义数量不变

#### Scenario: Disable Shell without disabling collectors

- **WHEN** 用户关闭 Shell 工具插件并完成重载
- **THEN** 后续轮次没有 shell 工具，但 Collector 网关仍可用

### Requirement: Reads can run concurrently and writes are exclusive per workspace

系统 SHALL 对同一固定工作区使用共享读写调度器。read、grep 和明确声明只读的 Collector 可在默认 4 个读槽内并发；write 和 shell MUST 独占工作区，且不与读操作同时运行。模型生成不持有该锁。

#### Scenario: Concurrent reads across sessions

- **WHEN** 两个会话同时进行独立只读操作
- **THEN** 它们可以并发运行，并按 tool_call_id 返回各自结果

#### Scenario: Serialize writes

- **WHEN** 两个会话同时写文件或运行 Shell
- **THEN** 只有一个 exclusive 操作运行，另一个可见地等待，取消/失败后释放锁

### Requirement: Sandbox is simple, explicit, and optional

系统 SHALL 提供 `sandbox.enabled` 与 `sandbox.network` 配置。开启时使用 bubblewrap 约束内置文件/Shell，创建隔离失败 MUST 返回 `sandbox_unavailable`；关闭时按宿主权限运行，并保留取消、超时和调度规则。可信 Python Collector/Channel 不被描述为受该沙箱保护。

#### Scenario: Sandbox cannot be started

- **WHEN** `sandbox.enabled=true` 但宿主缺少 bubblewrap 或隔离环境创建失败
- **THEN** Shell 返回 `sandbox_unavailable`，不自动按主机权限重试

#### Scenario: Run with sandbox disabled

- **WHEN** 用户显式设置 `sandbox.enabled=false` 并开始下一轮
- **THEN** Shell 按服务进程权限执行，同时继续遵守工作区调度、取消和超时规则

### Requirement: Memory and history are readable files

系统 SHALL 提供工作区根 `AGENTS.md`、按配置时区的 `Memory/YYYY-MM-DD.md`、可编辑 `History/<session>.md`、只读 Runtime、事件和 Artifact。Agent MUST 使用普通 read/write/grep 维护 Memory 和 History，不增加记忆专用工具或向量索引。活动 turn 捕获的 AGENTS 和工具定义保持稳定，修改从下一轮或新分支生效。

Runtime MUST provide a session-scoped read-only logical file `Runtime/self.json`. Its stable path MUST be included in the built-in runtime instruction so the model can discover it without knowing its own ID. Its resolution MUST use the current Agent session context, so concurrent sessions reading the same logical path receive different metadata; it MUST NOT be implemented as a shared `Runtime/current.json` file.

#### Scenario: Keep instructions stable during a turn

- **WHEN** Agent turn 已经开始后用户修改 `AGENTS.md`
- **THEN** 当前 turn 继续使用已捕获内容，下一轮或新分支才读取修改后的文件

#### Scenario: Write daily memory with ordinary files

- **WHEN** Agent 判断一条信息值得保留并调用普通 `write`
- **THEN** 内容写入配置时区对应的 `Memory/YYYY-MM-DD.md`，系统不额外创建记忆工具或自动日记

#### Scenario: Read the current session identity

- **WHEN** 两个 Agent 会话并行调用 `read("Runtime/self.json")`
- **THEN** 每个调用返回其自身的 `session_id`、`turn_id` 和 `branch_id`，不会读取或覆盖另一个会话的元数据

### Requirement: Compaction uses a fixed configurable budget

系统 SHALL 复用 `SummarizationMiddleware`。默认完整上下文预算为 200,000 tokens，达到 180,000 时最多进行一次压缩，保留最近 40,000 tokens 的完整消息组；统计按 message 粒度，未知模型容量要求显式配置。必须设置 `trim_tokens_to_summarize=None`，保留 AGENTS、系统提示、工具定义和完整 ToolMessage 配对。压缩失败或压缩后仍超限 MUST 保留旧上下文并返回明确错误。

#### Scenario: Compact a long conversation

- **WHEN** 完整请求达到 180,000 tokens
- **THEN** 系统调用摘要模型一次，保存摘要及覆盖范围，再重新计算预算；不循环压缩

#### Scenario: Running compact command

- **WHEN** 运行中收到 `/compact`
- **THEN** 命令排队并在下一次模型返回边界处理，不返回旧式 409

### Requirement: Checkpoints and side effects are retained safely

系统 SHALL 以 LangGraph thread 保存执行状态，并记录 `created_at`、`updated_at` 和 `last_checkpoint_at`。由于 SQLite saver 不能安全删除链上任意中间 checkpoint，普通压缩/分支 MUST NOT 删除中间行；整条 thread 只有在显式保留策略、过期、无活动轮次和无分支/Artifact 引用时才可清理。工具执行前后 MUST 记录稳定键和事实，未知副作用不得自动重做。

#### Scenario: Fork without editing old history

- **WHEN** 用户编辑自己的历史输入并确认 fork
- **THEN** 系统从旧 checkpoint/消息节点建立新分支，旧分支和模型输出不变

#### Scenario: Crash during a side effect

- **WHEN** 外部动作开始后服务在完成事件提交前退出
- **THEN** 会话标记 interrupted/outcome_unknown，恢复时不自动重做该工具
