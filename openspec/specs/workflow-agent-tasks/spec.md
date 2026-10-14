# workflow-agent-tasks

## Purpose

说明逐项选择普通模型或 Agent 执行、工具白名单、提示词继承和结果适配，保证任务之间隔离且 Agent 会话不是第二份 Workflow 结果。实现与验收证据见 Git 历史和本地分析稿；历史验证不能替代当前版本回归。

## Requirements

### Requirement: Task-level Agent execution

Workflow SHALL allow each analysis task to choose single-call LLM execution or Agent execution independently. The choice SHALL NOT apply to the whole Analyze subgraph.

#### Scenario: Mixed analysis execution

- **WHEN** one Workflow has one task with `agent_mode=false` and another with `agent_mode=true`
- **THEN** the first task uses `AIService.execute()` and the second task uses an Agent Session
- **AND** both results are returned through the existing `AnalysisResult` contract

#### Scenario: Task-specific model and prompts

- **WHEN** an Agent task declares its own model and prompt fields
- **THEN** the Agent Session uses that task's model, system prompt, input prompt and user prompt
- **AND** unset system/input prompts inherit the Workflow fields, while user_prompt and tools remain scoped to the task

### Requirement: Task-specific Agent tools

An Agent task SHALL support an optional tool allowlist scoped to that task. `null` SHALL inherit enabled Agent tools, an empty list SHALL disable tools for that task, and a non-empty list SHALL restrict execution to the listed tools.

#### Scenario: Tool allowlist

- **WHEN** two Agent tasks select different tool lists
- **THEN** each task's Agent Session exposes only its own selected tools
- **AND** one task's selection does not change global Agent settings or the other task

### Requirement: Agent result compatibility

The Workflow Agent adapter SHALL convert a completed, failed, cancelled or timed-out Agent turn into the existing `AnalysisResult` shape. Agent executions SHALL expose their session ID for process inspection, while single-call LLM executions SHALL leave that field empty.

#### Scenario: Agent process inspection

- **WHEN** an Agent task completes
- **THEN** the Workflow report can open the associated Agent Session and display existing Agent events, reasoning and tool calls
- **AND** the displayed Agent Session does not become a second source of Workflow result state

### Requirement: Agent Task 继承相同 Prompt 优先级

Agent Task SHALL 使用 Task 独立覆盖优先、否则继承 Workflow 的系统和输入模板，有效输入模板 SHALL 非空白，并使用 Task 自己的必填差异。Agent 运行规则 SHALL 与有效系统指令合入同一系统消息，首轮 SHALL 不追加固定执行 Human 消息。

#### Scenario: Task Prompt 在恢复与分支中保留

- **WHEN** Agent Task 会话重启或从完成轮次 fork
- **THEN** 三段 Prompt 保持原值，来源不重复注入，后续聊天不改变父 Workflow 首轮结果
