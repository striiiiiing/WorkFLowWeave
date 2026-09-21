## ADDED Requirements

### Requirement: Agent executes existing plugin capabilities as individual calls

系统 SHALL 提供基于 LangGraph 的独立 Agent 会话，复用既有 Collector、Channel、Schema 和资源解析能力。每次插件 call MUST 只执行一次采集或投递，且保留原业务结果状态。

#### Scenario: Read a Schema and collect once

- **WHEN** Agent 查询已配置来源的调用 Schema 并提交合法调用参数
- **THEN** 系统从同一插件声明派生 Schema，使用固定实例配置和本次调用参数调用 CollectorManager 一次，并返回真实结果

#### Scenario: Reject instance-level overrides

- **WHEN** Agent 在调用参数中覆盖未标记为调用层的连接或凭据字段
- **THEN** 系统返回字段错误，不修改实例且不执行外部调用

#### Scenario: Preserve uncertain delivery

- **WHEN** 渠道发送可能已经发生但未取得确定回执
- **THEN** 系统保留 delivery_uncertain/结果未知，不自动重发，也不展示为明确成功

### Requirement: Tools are registered through plugins with a compact default surface

系统 SHALL 通过既有插件注册机制发布工具插件，默认只提供 plugin、read、write、grep、shell 五个模型工具。采集器和渠道数量增长 MUST NOT 自动增加顶层工具 Schema 数量。

#### Scenario: Add another collector

- **WHEN** 新增一个有效 Collector 插件和来源实例
- **THEN** Agent 可通过 plugin 发现并调用它，绑定给模型的顶层工具集合不增加该 Collector 的专用工具

#### Scenario: Disable an optional tool plugin

- **WHEN** 用户关闭一个工具插件并成功重载
- **THEN** 后续轮次不导入/注册该插件能力，工具定义不进入提示词，旧工具名调用返回不可用

#### Scenario: Disable file tools

- **WHEN** 文件读写工具被关闭
- **THEN** Agent 不通过隐藏的记忆工具读写文件，系统明确展示实际剩余能力，核心仍加载既有 AGENTS.md

### Requirement: Reads may run concurrently and writes are exclusive

系统 SHALL 为所有 Agent 会话和 Agent 文件 API 共享一个执行调度边界，允许受配置并发数限制的只读操作并行；exclusive 操作运行时 MUST 不存在其他读取或 exclusive 操作。Shell 与 Channel 发送 MUST 按 exclusive 执行。

#### Scenario: Concurrent independent reads

- **WHEN** 模型请求多个独立只读调用且容量充足
- **THEN** 它们可以并发执行，各自结果与原 tool_call_id 对应

#### Scenario: Serialize writes across sessions

- **WHEN** 两个会话同时写文件或执行 Shell
- **THEN** 最多一个 exclusive 操作执行，另一个显示等待；取消或失败后正确释放调度资源

#### Scenario: Collector has no read declaration

- **WHEN** 第三方 Collector 没有声明可并发读取
- **THEN** Agent 将该调用按 exclusive 执行，不根据模型参数或插件名字判断为只读

### Requirement: Sandbox behavior is explicit and can be disabled

系统 SHALL 提供可关闭的简单 Agent 文件/Shell 沙箱；开启时约束工作区访问和 Shell 进程，关闭时按宿主权限执行。沙箱不可用 MUST 明确失败，不得静默切换执行模式。

#### Scenario: Prevent sandboxed path escape

- **WHEN** 开启沙箱的文件工具或 Shell 尝试通过父目录或符号链接访问未暴露的宿主文件
- **THEN** 操作失败且错误可见

#### Scenario: Missing operating-system sandbox

- **WHEN** 配置要求 Shell 沙箱，但平台、依赖或内核不支持
- **THEN** Shell 报告 sandbox_unavailable，用户可以显式关闭沙箱或工具

#### Scenario: Disable sandbox

- **WHEN** 用户保存 sandbox.enabled=false 并开始新轮次
- **THEN** Agent 文件/Shell 工具按宿主权限访问，仍遵守取消、超时、插件启停和读写调度

#### Scenario: Existing Python plugin boundary

- **WHEN** Agent 调用现有可信 Python Collector 或 Channel
- **THEN** 插件通过既有服务端 Manager 执行，系统不声称它受 Shell 沙箱隔离

### Requirement: Instructions and memory use readable files

系统 SHALL 持续加载工作区根 AGENTS.md，并向 Agent 提供按日 Memory 和可编辑 History 笔记文件。记忆写入 MUST 通过通用文件能力完成，不增加专用记忆工具或另一套自动日记服务。

#### Scenario: Keep instructions after compaction

- **WHEN** 会话已压缩历史且下一次请求发往模型
- **THEN** 当前 AGENTS.md 仍完整存在于常驻上下文；不能因摘要而丢失

#### Scenario: Write daily memory

- **WHEN** Agent 判断某条信息值得长期保留
- **THEN** 它可使用普通写工具更新配置时区对应的 Memory/YYYY-MM-DD.md

#### Scenario: Edit historical notes without rewriting execution facts

- **WHEN** Agent 更新 History 中自己的 Markdown 笔记
- **THEN** 文件内容改变，但真实工具回执和已经发生的执行状态不被改写或重放

### Requirement: Context compaction uses configurable model budgets

系统 SHALL 使用可配置模型容量与输出预留计算活跃消息预算，并复用现成摘要中间件。完整工具输出 MUST 文件化；自动压缩 MUST 保留最近合法消息组、任务约束、事实引用和未完成状态。

#### Scenario: Larger model context

- **WHEN** 用户选择并配置更大上下文模型
- **THEN** 压缩触发和保留预算随容量变化，不被固定小消息数或固定小 Token 窗口限制

#### Scenario: Unknown context capacity

- **WHEN** 提供方未提供可靠上下文容量且用户没有配置
- **THEN** 系统明确要求容量配置，不猜测默认小窗口

#### Scenario: Large tool output

- **WHEN** 工具输出超过预览预算
- **THEN** 模型收到明确截断标记和正文文件引用，可按需读取，历史仍保存可用原文

#### Scenario: Compaction fails or cannot fit

- **WHEN** 摘要模型失败，或一次压缩后上下文仍不能容纳
- **THEN** 系统保留先前消息并返回明确错误，不以错误文本替代摘要、不静默丢消息、不循环压缩

### Requirement: Interrupted side effects are never silently replayed

系统 SHALL 持久化稳定工具调用键和执行事实；已完成调用 MUST 复用结果，中断且结果未知的副作用 MUST NOT 自动重做。

#### Scenario: Crash after a send starts

- **WHEN** 服务在渠道发送已开始但完成事件尚未提交时退出
- **THEN** 重启后轮次标记 interrupted，调用结果标记未知，不自动再次调用渠道

#### Scenario: Continue a conversation after interruption

- **WHEN** 用户在中断会话中发新消息且原 checkpoint 有效
- **THEN** 系统先建立工具调用与结果配对完整的可继续上下文，再处理新消息，不执行旧 pending 工具任务

#### Scenario: Missing checkpoint

- **WHEN** 执行 checkpoint 缺失或损坏
- **THEN** 系统明确显示不可继续，仍允许读取可用历史文件，不根据可编辑 Markdown 猜测执行位置
