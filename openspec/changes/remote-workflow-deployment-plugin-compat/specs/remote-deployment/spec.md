## Purpose

定义本地前端连接独立远端 Workflow 后端时必须保持的健康、运行、流式进度和终态可用性，确保部署验收覆盖真实业务链路而不是只检查进程是否启动。

## ADDED Requirements

### Requirement: Frontend can use a remote Workflow backend

The system SHALL allow the frontend server to use an explicitly configured remote Workflow backend base URL, and SHALL expose the selected backend origin in diagnostics without exposing credentials.

#### Scenario: Remote health and resource queries

- **WHEN** the frontend is configured with the remote backend origin and requests health, plugin inventory, and workflow resources
- **THEN** each request reaches the remote backend, returns a valid response, and diagnostics identify the remote origin

#### Scenario: Backend is unavailable

- **WHEN** the configured remote backend cannot be reached or returns a non-success response
- **THEN** the frontend reports a connection error with the affected operation and does not display a fabricated healthy or empty state

### Requirement: Remote Workflow run has a real stream and terminal record

The system SHALL support triggering a Workflow on the remote backend, receiving the existing snapshot SSE protocol, and querying the same run after the stream reaches a terminal state.

#### Scenario: Run and observe a completed Workflow

- **WHEN** a valid Workflow is triggered through the remote backend
- **THEN** the client receives a snapshot with a session identity, observes progress, receives a terminal status, and can query a matching final record after the connection closes

#### Scenario: Stream disconnect

- **WHEN** the SSE connection disconnects before terminal status
- **THEN** the client reconnects or explicitly reports the interruption, preserves the last known session identity, and never triggers a second Workflow run implicitly
