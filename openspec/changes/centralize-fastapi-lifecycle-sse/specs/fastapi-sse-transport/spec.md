# FastAPI SSE Transport

## ADDED Requirements

### Requirement: event streams use native FastAPI SSE
所有 interaction 事件流 MUST 使用 FastAPI 原生 `EventSourceResponse` 和 `ServerSentEvent`，并输出标准 `text/event-stream` 响应。

#### Scenario: workflow event is encoded as an SSE event
- **WHEN** 客户端订阅 workflow 事件流并产生一个事件
- **THEN** 响应包含标准 SSE 的 `event`、`id` 和 `data` 字段
- **AND** 业务 payload 可按 JSON 解析

#### Scenario: client disconnect releases subscription
- **WHEN** 客户端在事件流过程中断开连接
- **THEN** 生成器停止向该客户端发送事件
- **AND** 该订阅、监听任务和临时资源被释放
- **AND** 共享的 workflow 或 Agent 任务不会仅因该断开而被取消

### Requirement: existing event semantics remain stable
原有事件名、事件 ID、会话过滤、游标和 `Last-Event-ID` 语义 MUST 保持不变；迁移 MUST NOT 要求客户端修改这些业务字段。

#### Scenario: resume from Last-Event-ID
- **WHEN** 客户端带有有效 `Last-Event-ID` 重新订阅
- **THEN** 服务按既有游标语义发送后续可见事件
- **AND** 事件使用 FastAPI 原生 SSE 格式传输
