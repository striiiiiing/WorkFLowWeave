# workflow-agent-runtime-port

## Purpose

说明任务级 Agent 在当前 WorkflowRunner、AgentService、MCP 和前端架构中的接线与首轮身份，不引入源端已淘汰的运行时。未完成的实现与验收仍由所属活动变更管理，历史验证不能替代当前版本回归。

## Requirements

### Requirement: Agent tasks use the current Workflow runtime

The system SHALL execute Task and FanIn Agent turns through the current WorkflowRunner and WorkflowContext without restoring the retired WorkflowService or PluginGateway.

#### Scenario: Mixed LLM and Agent tasks

- **WHEN** one Workflow contains both ordinary and Agent analysis tasks
- **THEN** ordinary tasks use AIService and Agent tasks use the injected AgentService
- **AND** both results are archived by the current checkpoint subscription

### Requirement: First-turn identity follows execution epochs

The system SHALL derive Agent operation identity from the Workflow session, persistent execution epoch, stage and task identity.

#### Scenario: Resume after an Agent completed before its parent checkpoint

- **WHEN** the same Workflow execution epoch resumes a completed Agent task
- **THEN** the first accepted Agent turn result is reused without repeating tools

#### Scenario: Explicitly redo an analysis stage

- **WHEN** a user explicitly redoes the analysis stage with a new execution epoch
- **THEN** the system creates a new Agent session for that task

### Requirement: Preserve current MCP and frontend architecture

The system SHALL preserve the existing MCP binding, FastAPI SSE and frontend module boundaries while exposing Agent task results and session links.

#### Scenario: Open an Agent task from a run report

- **WHEN** an analysis or aggregate report includes an Agent session identifier
- **THEN** the report opens the existing Agent session through the current module routes
- **AND** later messages do not change the Workflow archive
