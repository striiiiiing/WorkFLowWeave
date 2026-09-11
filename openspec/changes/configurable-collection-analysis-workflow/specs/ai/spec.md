## Purpose

为 Workflow 分支和后续轻量 Agent 提供独立、可复用的模型执行能力，使系统提示词、模型配置、工具及运行结果具有一致接口，并支持离线验证和真实模型接入。

## ADDED Requirements

### Requirement: 模型与提示词隔离

AI 执行 SHALL 使用指定模型、系统提示词和自定义参数，拒绝 temperature、top_k 和会覆盖请求结构的保留参数，支持离线 Mock 和 HTTP 模型。

#### Scenario: 不同分支配置

- **WHEN** 两个分支引用不同 AI 配置
- **THEN** 各自使用独立模型参数和提示词，完整保留输入

#### Scenario: 敏感配置

- **WHEN** 模型调用失败
- **THEN** 错误包含可诊断原因且不暴露 API 凭据

### Requirement: 工具与有界执行

AI 执行 SHALL 支持已注册工具的 schema 和结果关联，拒绝未知工具或错误参数，并约束模型与工具执行时间。

#### Scenario: 工具执行

- **WHEN** 模型返回工具调用
- **THEN** 验证参数，执行所选工具并使用对应调用 ID 返回结果

#### Scenario: 模型超时

- **WHEN** 模型未在指定期限完成
- **THEN** 返回可识别失败，调用者可以保留其他分支结果
