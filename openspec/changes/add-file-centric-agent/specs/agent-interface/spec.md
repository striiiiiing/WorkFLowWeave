## ADDED Requirements

### Requirement: Agent has a dedicated conversational interface

前端 SHALL 提供独立 Agent 导航、会话列表、流式对话和按需详情抽屉；复用既有模型资源、Schema 表单与报告展示，不将 Agent 会话伪装成 Workflow 运行。

#### Scenario: Ask about collected information

- **WHEN** 用户选择已配置模型并发送问题
- **THEN** 页面显示模型回复、相关采集动作与实际结果，默认呈现可读内容，原始 JSON 可展开

#### Scenario: Narrow screen

- **WHEN** 用户在手机宽度访问会话
- **THEN** 对话保持单列可读，会话、文件和设置通过抽屉访问

### Requirement: Session API has one active turn and idempotent submission

Agent API SHALL 使用独立命名空间、长期 session_id 和单次 turn_id，每个会话同时只运行一轮；消息提交 MUST 使用 request_id 去重。

#### Scenario: Repeat the same message request

- **WHEN** 客户端重试同 request_id 与相同文本
- **THEN** 返回原 turn_id 与状态，不创建第二轮或重复工具调用

#### Scenario: Submit during an active turn

- **WHEN** 当前会话仍在运行且收到另一个新消息提交
- **THEN** API 返回明确 turn_active 冲突，不静默排队或覆盖当前消息

### Requirement: Stream reconnection preserves event identity

系统 SHALL 通过 SSE 推送与持久事件一致的事件 ID，支持游标续传；浏览器断开 MUST NOT 隐式取消后台轮次。

#### Scenario: Reconnect after a temporary disconnect

- **WHEN** 浏览器携带最后 event_id 重连
- **THEN** 服务回放缺失事件并连续接入实时流，界面按 ID 去重，不漏掉已提交消息或重复显示工具结果

#### Scenario: Explicit cancellation

- **WHEN** 用户点击停止
- **THEN** 前端发取消请求并在后端确认后展示终态，已经完成的副作用不显示为撤销

### Requirement: Users can inspect and edit Agent files

前端 SHALL 提供 AGENTS、Memory、可编辑历史笔记、只读原始记录及工具输出的文件访问。文件编辑 MUST 使用与 Agent 相同的写调度和版本冲突检查。

#### Scenario: Agent changed a file while a user was editing

- **WHEN** 用户提交的文件版本与当前内容不同
- **THEN** API 返回冲突，前端保留用户草稿并明确提示，不静默覆盖 Agent 的新内容

#### Scenario: View execution history

- **WHEN** 用户查看原始历史或工具正文
- **THEN** 页面按需读取可用文件并标注只读/截断/缺失，不使用可编辑笔记推断真实运行状态

### Requirement: Tool and sandbox settings show actual behavior

前端 SHALL 提供插件开关与沙箱配置入口，并展示后端实际启用工具和执行状态；不得在前端自行实现权限或并发分类。

#### Scenario: Disable Shell tool

- **WHEN** 用户关闭 Shell 插件并完成重载
- **THEN** 后续轮次不再绑定 Shell 工具，页面准确显示关闭状态

#### Scenario: Sandbox is disabled or unavailable

- **WHEN** 后端报告沙箱关闭或不可用
- **THEN** 页面区分「按宿主权限运行」与「无法启动隔离」，不将不可用视为已自动关闭

### Requirement: Context usage and compaction are visible without losing chat history

前端 SHALL 展示上下文预算、实际值/估算来源以及压缩结果，并允许空闲时手动触发同一压缩逻辑。

#### Scenario: Automatic compaction succeeds

- **WHEN** 后端发出 context.compacted
- **THEN** 对话显示轻量压缩提示和可查看摘要，旧消息仍可从原始事件查看，不从 UI 删除

#### Scenario: Compaction fails

- **WHEN** 摘要或上下文预算检查失败
- **THEN** 界面显示可读错误与保留的历史，不显示压缩成功或虚构精确 Token 用量
