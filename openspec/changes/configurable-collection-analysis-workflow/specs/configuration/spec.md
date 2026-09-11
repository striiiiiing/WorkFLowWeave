## Purpose

管理本地自托管服务的系统配置和可复用资源，使 Workflow 可以在严格校验后的确定配置上运行，并保证修改模板或连接设置不会改变已启动运行的含义。

## ADDED Requirements

### Requirement: 严格配置与资源复用

系统 SHALL 从 JSON 加载系统和插件设置，拒绝未知公共字段、无效资源 ID、无效引用和不属于 Collector 的 Setter 模板；所有资源可保存、查询和复用。

#### Scenario: 错误配置不落盘

- **WHEN** 保存带未知字段、缺失引用或跨 Collector 模板的 Workflow
- **THEN** 返回含可修正原因的校验错误且原资源保持不变

#### Scenario: 模板显式覆盖

- **WHEN** 实例和匹配模板包含同名 Setter
- **THEN** 实例值覆盖模板值，其他模板字段保持

### Requirement: 确定快照与原子写入

系统 SHALL 在启动运行时保存引用资源的独立快照；并发写入不得产生截断 JSON，删除被引用资源必须返回冲突。

#### Scenario: 修改不影响运行

- **WHEN** 运行开始后用户修改 AI 或 Setter 模板
- **THEN** 当前 session 仍使用启动时的值

#### Scenario: 凭据引用

- **WHEN** 配置模型或邮件凭据
- **THEN** 只保存环境变量引用，查询配置和存档不返回解析出的秘密
