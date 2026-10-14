# workflow-prompts

## Purpose

说明当前架构已采用的三层提示词、独立覆盖、空来源执行和汇总输入顺序；未移植的旧优化和资源迁移不进入现行契约。未完成的实现与验收仍由所属活动变更管理，历史验证不能替代当前版本回归。

## Requirements

### Requirement: 必填的三层提示词

系统 SHALL 按 `[SystemPrompt, HumanPrompt(input), HumanPrompt(差异)]` 发送普通与 Agent 分析请求。两层 HumanPrompt 的输入模板及差异指令 SHALL 由用户填写且为非空白内容（输入模板展开后的业务正文 MAY 为空），系统提示词 MAY 为空。Task 的前两层覆盖 SHALL 各自优先于 Workflow 共享值，未设置 SHALL 继承共享字段；仅输入模板 SHALL 展开 `{input}`。

#### Scenario: 独立覆盖与字面差异

- **WHEN** Task 只覆盖系统提示词，差异包含 `{input}`
- **THEN** 请求使用 Task 系统、Workflow 输入模板、字面差异三条消息

#### Scenario: 必填校验

- **WHEN** 用户遗漏差异或提交空白输入模板/差异
- **THEN** 保存明确失败并定位对应字段，系统不自动填写指令；切换 Agent 模式也不生成或清空用户填写的差异

### Requirement: 无采集源的提示词执行

Workflow SHALL 允许显式空采集源列表，使用空字符串作为输入执行分析、汇总及投递。全空策略 SHALL 仅适用于配置了采集源但没有有效采集结果的运行。

#### Scenario: 仅提示词的 Workflow

- **WHEN** 用户保存并执行 `sources=[]` 的 Workflow
- **THEN** 保存成功，不调用采集器，以空输入继续三层提示词分析和后续阶段，不因全空策略停止

#### Scenario: 已配置来源没有内容

- **WHEN** Workflow 配置了来源但采集均返回空结果
- **THEN** 继续按原全空策略处理，不将此次运行当作无采集源的提示词执行

### Requirement: 汇总输入的默认顺序与显式覆盖

启用模型的常规汇总 SHALL 使用独立的三层消息；当 `order` 为空时，输入顺序 SHALL 默认包含 `$input`，随后按 Task 声明顺序加入上一阶段输出，差异 SHALL 使用汇总自身字段。用户可在前端显式编辑 `order` 覆盖默认顺序。关闭模型时仅进行纯文本拼接，不发送 PromptList。

#### Scenario: 多任务乱序完成

- **WHEN** 分析任务以不同顺序完成且汇总未指定 order
- **THEN** 汇总输入先包含原始 `$input`，再包含按声明顺序排列的分析输出；完成顺序不影响内容顺序

#### Scenario: 用户省略原始输入

- **WHEN** 用户在前端显式保存仅含分析 Task ID 的非空 order
- **THEN** 普通与 Agent 常规汇总均只拼接所选分析结果，不再加入 `$input`
