## Purpose

约束 Workflow 绑定 Agent 的 MCP 携带边界，使一次 Workflow 运行只能看到绑定声明的 MCP，并能在诊断或运行记录中核验实际选择，而不是依赖全局 Agent 默认值。

## ADDED Requirements

### Requirement: Workflow-bound Agent carries only its declared MCP set

The system SHALL resolve the Agent bound by a Workflow together with its declared MCP identifiers, pass only that set to the run, and preserve the binding identity in the run diagnostics. A missing, disabled, or unauthorized MCP SHALL fail the run before external side effects and SHALL NOT fall back to a global MCP set.

#### Scenario: Bound Agent receives the requested MCP

- **WHEN** a Workflow references an enabled Agent with a declared MCP set
- **THEN** the run completes with the bound Agent identity and the exact MCP IDs visible in diagnostics or the final record

#### Scenario: Unbound MCP is requested

- **WHEN** the Workflow requests an MCP that is missing, disabled, or not allowed for the bound Agent
- **THEN** the run fails with an explicit binding error before notification or other external side effects, and no undeclared MCP is attached

### Requirement: MCP identity is stable across reconnect and resume

The system SHALL retain the Workflow, Agent, and MCP binding identities across SSE reconnect and supported resume queries.

#### Scenario: Reconnect after progress

- **WHEN** a client reconnects to a running or completed session
- **THEN** the returned snapshot or final query retains the same Workflow, Agent, and MCP identities without re-running the Agent
