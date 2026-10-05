## ADDED Requirements

### Requirement: Agent Task 继承相同 Prompt 优先级

Agent Task SHALL 使用 Task 独立覆盖优先、否则继承 Workflow 的系统和输入模板，并使用 Task 自己的必填差异。Agent 运行规则 SHALL 与有效系统指令合入同一系统消息，首轮 SHALL 不追加固定执行 Human 消息。

#### Scenario: Task Prompt 在恢复与分支中保留

- **WHEN** Agent Task 会话重启或从完成轮次 fork
- **THEN** 三段 Prompt 保持原值，来源不重复注入，后续聊天不改变父 Workflow 首轮结果

### Requirement: Agent 汇总永不采用单任务优化

Agent 汇总 SHALL 始终使用常规三层 Prompt，即使一个 Task、模型相同且存储的优化标志为 true。前端 SHALL 不显示 Agent 汇总的“采用单任务优化”选项。

#### Scenario: 同模型单 Agent 汇总

- **WHEN** 仅一个分析 Task，Agent 汇总模型与其相同
- **THEN** Agent 首轮使用汇总自身系统、上一阶段结果输入、汇总差异三条消息，不包含分析 Task 差异或作为 AI 角色注入的分析回复
