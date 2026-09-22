## ADDED Requirements

### Requirement: Agent exposes independent sessions, branches, and commands

系统 SHALL 提供独立 `/api/agents` 命名空间、长期 session_id、树形 branch_id 和单次 turn_id。普通命令 SHALL 使用 `{channel, session, priority}` 信封，并按 stop、命令、普通对话的顺序处理。会话工作目录不能由命令修改。

#### Scenario: Start from latest Workflow result

- **WHEN** 用户点击 Workflow 历史中的“从最新结果继续”
- **THEN** 前端创建 Agent session，显示来源 Workflow session 和可选择模型

#### Scenario: Fork an edited user message

- **WHEN** 用户编辑自己的消息并确认 fork
- **THEN** 前端显示新 branch，旧消息树保持只读；模型输出没有编辑入口

#### Scenario: Queue append and compact

- **WHEN** 活动 turn 收到 `/append` 或 `/compact`
- **THEN** 页面显示已排队，并在下一次模型返回边界收到相应事件

### Requirement: Message submission is idempotent and stream is resumable

`POST /sessions/{id}/messages` MUST 接受 `request_id` 并对相同内容去重；同一会话一次只运行一轮普通模型执行。SSE MUST 使用持久事件 ID 支持 `Last-Event-ID/after` 回放，断线不取消后台轮次。

#### Scenario: Retry a message request

- **WHEN** 客户端以同一 request_id 和相同文本重试
- **THEN** 服务返回原 turn_id，不创建第二轮或重复工具调用

#### Scenario: Reconnect after disconnect

- **WHEN** 浏览器带最后事件 ID 重连
- **THEN** 服务回放缺失事件并接入实时事件，前端按 ID 去重

### Requirement: Users can inspect files and actual tool behavior

前端 SHALL 提供会话/分支树、Workflow 来源、五个工具状态、AGENTS、Memory、History、Runtime、Artifacts 和 Catalog 抽屉。文件保存 MUST 使用 ETag/If-Match 和后端相同的写锁。设置页 SHALL 区分工具关闭、沙箱关闭和沙箱不可用。

#### Scenario: File version conflict

- **WHEN** 用户提交的 ETag 已过期
- **THEN** API 返回冲突，前端保留草稿并要求重新读取，不静默覆盖 Agent 修改

#### Scenario: Show compaction

- **WHEN** 后端发出 `context.compacted`
- **THEN** 页面显示摘要和覆盖范围，聊天旧消息仍可通过历史查看
