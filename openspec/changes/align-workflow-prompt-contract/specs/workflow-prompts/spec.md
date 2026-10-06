## ADDED Requirements

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

### Requirement: 普通汇总单任务优化

普通汇总 SHALL 提供默认开启的 `single_task_optimization`，前端 SHALL 仅在高级模式显示“采用单任务优化”。只有一个分析 Task 且汇总与 Task 使用相同供应商配置和模型时 SHALL 复现原 Task 三条消息，追加 AI 回复与汇总差异；其余情况 SHALL 使用常规三层方案。

#### Scenario: 同模型优化

- **WHEN** 只有一个成功 Task、汇总模型相同且优化开启
- **THEN** 汇总实际请求为 `[Task System, Task 输入 Human, Task 差异 Human, AI(Task 回复), 汇总差异 Human]`

#### Scenario: 关闭或不同模型

- **WHEN** 用户关闭优化或汇总模型不同
- **THEN** 汇总使用自己的三层消息，其第二层输入由汇总 order 决定；空 order 为原始 `$input` 加上一阶段结果，显式 order 可省略 `$input`

### Requirement: 显式旧资源迁移

系统 SHALL 仅在持久化读取边界迁移旧 prompt，当前 API SHALL 拒绝旧字段；无法得到必填差异时 SHALL 明确报错并保留原文件。旧运行快照 SHALL 保持原消息语义并可继续恢复，不接受为新配置。

#### Scenario: 旧配置缺少指令

- **WHEN** 旧 Task prompt 只有 `{input}` 且没有差异
- **THEN** 迁移明确要求补齐差异，原文件与已发布资源视图保持不变

#### Scenario: 用户手工补齐旧配置

- **WHEN** 用户为只有 `{input}` 的旧分析或模型汇总补齐 `user_prompt` 后重新加载
- **THEN** 迁移保留用户补齐的指令并成功发布当前格式，不覆盖为提取出的空值
