## Purpose

把用户选择的多源采集、共享输入、并行分析、可选汇聚和有序通知组织为可以定时或手动触发的确定流程，并使失败恢复严格遵守原运行的配置与数据边界。

## ADDED Requirements

### Requirement: 共享输入与有序分支

首版 Workflow SHALL 将所有可用来源按声明顺序编排成共享输入，全部分支使用该输入，并按配置限制并发和保留输出顺序。

#### Scenario: 并行完成顺序不同

- **WHEN** 后声明分支先完成
- **THEN** 结果仍按声明顺序返回

#### Scenario: 串行配置

- **WHEN** 将分析并发设为 1
- **THEN** 不同时运行两个分析分支

### Requirement: 汇聚与失败策略

Workflow SHALL 支持可选汇聚、整体插入原始输入、来源各类失败/空策略、全部为空策略和分支部分成功策略。

#### Scenario: 不完整汇聚

- **WHEN** 一个分支失败且允许继续并标记
- **THEN** 保留成功结果并在汇聚内容说明输入不完整

#### Scenario: 禁止部分发送

- **WHEN** 分支部分失败且 send_partial 为 false
- **THEN** 不发送成功分支但保留结果

#### Scenario: 源全部为空

- **WHEN** 所有来源均无可用条目
- **THEN** 执行明确的停止或跳过策略

### Requirement: 触发与取消

Workflow SHALL 提供手动与内置定时触发，全局有界运行，防止定时任务重叠，并在取消/关闭时回收工作。

#### Scenario: 超长定时运行

- **WHEN** 上次运行仍活动时下次时间到达
- **THEN** 不重复启动同一 Workflow

#### Scenario: 取消中途运行

- **WHEN** 在采集或分析期间取消
- **THEN** 终止后续阶段，保存 cancelled，不能继续发通知

### Requirement: 确定恢复

Workflow SHALL 使用原 session 配置与保存内容恢复，跳过成功采集、分支和投递，必要材料不可用时报告边界。

#### Scenario: 修改配置后恢复

- **WHEN** 运行失败后来源和模型配置已修改
- **THEN** 恢复采用原快照且不重新请求已保存来源

#### Scenario: 通知失败后恢复

- **WHEN** 分析完成且仅一个目标投递失败
- **THEN** 只补发失败目标，不重跑分析或重发成功目标

#### Scenario: 缺少输入

- **WHEN** 恢复所需内容备份被关闭、过期或损坏
- **THEN** 返回明确不可恢复原因，不静默重新采集

### Requirement: 调度配置更新

Workflow SHALL 在有效配置更新后调整未来触发计划，禁用阻止新的手动和定时触发；已经受理的 session 保持原快照并通过显式取消入口停止。

#### Scenario: 禁用时已有运行

- **WHEN** Workflow 已有排队或活动 session，用户将 enabled 改为 false
- **THEN** 后续新触发被拒绝，已有 session 不因该变更被隐式取消

#### Scenario: 修改定时间隔

- **WHEN** 用户保存有效的新 interval_seconds
- **THEN** 后续调度使用新间隔，遵守单 Workflow 定时不重叠规则，不集中补发此前错过的触发
