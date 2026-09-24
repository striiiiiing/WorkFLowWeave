# Agent 重构连续性验收

依据：[已授权架构设计](../../../design-frontend-architecture/design.md) §5.1、§7、§8；原有会话、分支与文件冲突能力仍按所属规范回归。

## ADDED Requirements

### Requirement: Agent 路由内按会话保留输入与待确认请求

前端 SHALL 在连续访问 `/agents` 与 `/agents/:sessionId` 时按会话隔离输入和待确认请求；切换会话 SHALL 释放旧连接并隔离迟到回包，离开 Agent 区域不新增草稿持久化。

#### Scenario: 切换后返回未发送会话

- **WHEN** 用户在 A 输入内容，切换到 B 输入其他内容，再返回 A
- **THEN** A 与 B 各自输入保留，A 不显示 B 的输入或请求状态

#### Scenario: 旧会话请求迟到

- **WHEN** A 的请求在用户切换到 B 后返回
- **THEN** 回执只更新 A，不覆盖 B 的输入、当前事件或提交状态

### Requirement: Web 命令与流沿用统一渠道和逻辑请求身份

前端 SHALL 使用 `/api/channels/web/commands` 执行 Web 命令，使用 `/api/channels/web/sessions/{id}/events` 订阅事件；历史查询仍使用 Agent 查询 API。一次逻辑提交 SHALL 保持 request ID 和 payload，未知结果仅能以同一内容重试，修改内容 SHALL 成为新请求。

#### Scenario: 同内容重试与修改后发送

- **WHEN** 提交结果未知后用户重试原内容，或修改内容再发送
- **THEN** 原内容重试沿用 request ID，修改后使用新 ID，不自动重放整轮工具操作

#### Scenario: 停止与旧终态

- **WHEN** 普通发送仍在等待，用户发出停止，且流中随后到达旧轮次终态
- **THEN** 停止请求可独立提交，旧轮次终态不关闭当前新轮次；断线或离页不被当作后台取消

#### Scenario: 历史与实时事件接续

- **WHEN** 打开或重新连接会话
- **THEN** 按历史、当前会话快照、游标续传的顺序恢复，按会话与事件 ID 去重，仅在事件验证并接纳后推进游标，非法已知事件明确显示协议错误
