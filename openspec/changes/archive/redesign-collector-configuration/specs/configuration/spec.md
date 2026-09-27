# 采集器配置资源

## ADDED Requirements

### Requirement: 采集器实例和处理模板支持显示名称

配置资源 SHALL 为采集器实例和处理模板提供可选的 `display_name`，并保持内部 ID 作为稳定引用。

#### Scenario: 创建带名称的采集器实例

- **WHEN** 用户保存采集器实例并填写显示名称
- **THEN** 后端保存名称和内部 ID，工作流引用仍使用内部 ID

#### Scenario: 读取旧资源

- **WHEN** 旧资源没有 `display_name`
- **THEN** 后端仍接受该资源，前端可以使用内部 ID 展示，不要求迁移旧数据

### Requirement: 处理模板绑定采集器类型

配置模块 SHALL 校验处理模板的 `collector` 与引用它的采集器实例或工作流采集器类型一致。

#### Scenario: 保存不兼容模板

- **WHEN** 资源或工作流引用不同采集器类型的处理模板
- **THEN** 保存被拒绝并返回可定位的校验错误

#### Scenario: 保存兼容模板

- **WHEN** 模板和采集器使用同一注册类型
- **THEN** 配置可以保存并继续沿用现有模板合并顺序
