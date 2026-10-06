## ADDED Requirements

### Requirement: 三层提示词消息

系统 SHALL 为常规 Workflow AI 调用按顺序生成系统、包含本次输入的用户消息和本项差异用户指令；有效输入模板与差异指令 SHALL 非空白并由用户填写；系统与差异指令中的占位符 SHALL 按字面保留。分析项与 fan-in SHALL 默认同步共享系统提示词和第二层输入模板，并允许分别覆盖；前端 SHALL 在高级模式提供单项覆盖控件。

#### Scenario: 共享提示词与单项覆盖

- **WHEN** 用户修改共享系统提示词，同时某分析项设置独立系统提示词
- **THEN** 未覆盖的分析项和 fan-in 使用新共享值，已覆盖项继续使用其独立值

#### Scenario: 输入与差异指令

- **WHEN** 输入文本或差异指令包含字面 `{input}`
- **THEN** 只有输入模板的占位符被替换，输入文本和差异指令不被再次展开

#### Scenario: 单项输入模板覆盖

- **WHEN** 用户在高级模式为一个分析项设置独立的第二层输入模板
- **THEN** 该项使用覆盖值，其他分析项和 fan-in 继续跟随 Workflow 共享模板

### Requirement: 确定的 fan-in 输入与模型复用

系统 SHALL 按配置顺序把选定的原始输入和分析结果组装为 fan-in 的 `{input}`，并允许默认复用首个分析模型、选择其他来源或关闭复用。常规模式下模型复用 SHALL 不复制分析项的差异指令；普通单 Task 同模型优化 SHALL 依后续 align-workflow-prompt-contract 复现原 Task 三条消息并追加 AI 回复与汇总差异，Agent 汇总 SHALL 始终使用常规模式。

#### Scenario: 分析结果乱序完成

- **WHEN** 多个分析项以不同顺序完成
- **THEN** fan-in 用户输入仍按配置顺序构造，模型请求与差异指令保持独立

### Requirement: 旧提示词迁移

系统 SHALL 把旧资源模板提取为三层新字段并保留用户手工补齐值；无法提取必填差异时 SHALL 明确要求补齐且不覆盖原文件。仅内部旧执行快照解码 SHALL 保持原“模板在前、输入在后”的请求顺序；新 API SHALL 拒绝旧 `prompt` 字段。

#### Scenario: 重开旧工作流

- **WHEN** 加载使用旧 `prompt` 和 AIConfig 系统提示词的已存工作流
- **THEN** 迁移后的资源采用三层提示词；仅当全部必填指令已提取或手工补齐且验证成功时发布新格式
