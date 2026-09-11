## Purpose

为本地用户和外部客户端提供统一的配置、触发与查询接口，通过薄 CLI 复用服务业务逻辑，并提供清晰的验证错误、生命周期管理和可直接运行的离线示例。

## ADDED Requirements

### Requirement: 资源与运行 API

系统 SHALL 提供资源 CRUD、插件能力查询、Workflow 触发、session 查询、阶段内容查询、取消和恢复，且无效配置不得启动运行。

#### Scenario: 半配置运行

- **WHEN** 请求包含不存在的来源或不符合插件 schema 的配置
- **THEN** 返回 422 且没有新运行

#### Scenario: 异步触发

- **WHEN** 有效 Workflow 被触发
- **THEN** 返回 session ID，后续查询反映真实完成或失败状态

### Requirement: 薄 CLI 与启停

CLI SHALL 提供配置样例初始化、服务启动和 HTTP 调用入口，服务必须管理插件、调度器和任务的启停。

#### Scenario: 离线快速开始

- **WHEN** 按 README 初始化并触发样例
- **THEN** 无需密钥即可完成 Mock 采集、分析、文件通知和存档

#### Scenario: 服务关闭

- **WHEN** 有后台运行时关闭服务
- **THEN** 运行任务被等待或取消并保存状态，没有孤立任务
