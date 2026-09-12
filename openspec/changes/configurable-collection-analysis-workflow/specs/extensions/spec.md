## Purpose

在首版稳定流程上增加 proposal 的来源选择、Agent、可配置采集工具、健康监听与指令能力，并实现延后的外部触发和双向讨论，同时保持通知与会话的上下文隔离。

## ADDED Requirements

### Requirement: 分支来源与 Agent

系统 SHALL 默认使用全部来源，并允许分支选择存在的来源子集和单模型或有界多步 Agent 模式。

#### Scenario: 选择子集

- **WHEN** 分支只选两个已声明来源
- **THEN** 该分支输入仅含这两个来源且保持其顺序，其他分支仍使用默认全部来源

#### Scenario: 步数耗尽

- **WHEN** Agent 持续调用工具超过上限
- **THEN** 终止并返回可识别错误，保留调用轨迹

### Requirement: YAML Toolset 与健康监听

系统 SHALL 将已注册 Collector 暴露为有 schema 的可选工具，加载声明式 YAML Toolset，按插件健康检查结果向指定 channel 发出异常/恢复通知。

#### Scenario: 工具调用采集

- **WHEN** Agent 调用 Toolset 中定义的采集工具
- **THEN** 校验动态参数并调用所选 Collector，结果可追踪

#### Scenario: 健康去重

- **WHEN** 同一异常连续多次检测
- **THEN** 状态变化时通知，连续相同状态不刷屏，恢复后可以发恢复通知

### Requirement: Webhook 与指令

系统 SHALL 接收可配置外部触发，按配置执行命令及别名，通过与 API 相同的内部入口运行和查询，并限制不支持的命令。

#### Scenario: 外部触发

- **WHEN** 调用有效 Workflow 的 Webhook
- **THEN** 创建关联 trigger 元数据的 session

#### Scenario: 命令精确匹配

- **WHEN** 输入命令前缀相似但不相等的普通消息
- **THEN** 不得误执行控制命令

### Requirement: 连续讨论与会话隔离

系统 SHALL 在 ConversationChannel 中围绕明确关联的 Workflow session 提供多轮讨论，复用 AI 配置并保存会话，单向通知不得切换会话上下文。

#### Scenario: 新通知到达

- **WHEN** 用户正讨论 session A 时收到 session B 通知
- **THEN** 后续讨论仍关联 A，直至用户显式切换

#### Scenario: 会话并发

- **WHEN** 同一会话同时收到两条消息
- **THEN** 按消息顺序串行处理，不同会话可以并行

#### Scenario: 重启恢复会话

- **WHEN** 服务重启后再次访问会话
- **THEN** 保留关联 session 和已保存消息
