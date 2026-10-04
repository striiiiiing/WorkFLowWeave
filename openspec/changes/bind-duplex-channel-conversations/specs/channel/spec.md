# 渠道实例对话绑定

## ADDED Requirements

### Requirement: 双向渠道实例持有对话绑定

系统 SHALL 由渠道侧保存双向渠道实例到 Agent 对话的当前绑定，每个实例至多绑定一个当前对话。Agent 对话 SHALL NOT 保存渠道选择或依赖全局默认渠道。同一种渠道能力 SHALL 支持多个实例独立绑定。

#### Scenario: 同能力的多个实例

- **WHEN** 两个 QQ 渠道实例分别绑定对话 A 和对话 B
- **THEN** 两个绑定按实例 ID 独立保存
- **AND** 实例一的输入不能因使用相同 QQ 能力而进入实例二的对话

#### Scenario: 实例未绑定

- **WHEN** 未绑定对话的实例收到普通消息
- **THEN** 系统明确报告未绑定及未处理状态
- **AND** 不自动创建对话或选择某个旧对话

### Requirement: 实例绑定使用加锁内存缓存

系统 SHALL 启动时从渠道 SQLite 加载实例绑定到内存，接收路由与发送检查 SHALL 读取加锁的内存快照而非逐次查询 SQLite。系统 SHALL 先更新内存、再持久化改绑，串行化写入且不引入 Redis。

#### Scenario: 每次发送读取缓存

- **WHEN** 一个已绑定实例准备发送 Agent 输出
- **THEN** 当前绑定检查读取内存缓存
- **AND** 该检查不查询 SQLite 绑定表

#### Scenario: 改绑与持久化

- **WHEN** 用户修改实例绑定
- **THEN** 系统先在锁保护下更新内存，再串行写入 SQLite
- **AND** 成功响应等待持久化完成

#### Scenario: 持久化失败

- **WHEN** 更新内存后 SQLite 持久化失败
- **THEN** 系统明确返回错误并回滚事务、恢复之前的内存对话
- **AND** 绑定版本继续前进，旧在途输入与输出不能重新获得有效资格

### Requirement: 入站只进入实例绑定的对话

系统 SHALL 将收到的普通消息提交给该渠道实例绑定的 Agent 对话，保留 SDK 验证的来源、消息身份和回复路由。好友、群、发送者不同 SHALL NOT 自动创建另一个 Agent 对话。

#### Scenario: 同一实例收到不同对端的输入

- **WHEN** 一个实例绑定对话 A，并依次收到来自两个好友的消息
- **THEN** 两条消息进入对话 A
- **AND** 两条消息的来源、去重身份和可信回复地址仍分别保留

### Requirement: 入队与 Agent 操作结果分离

SDK 接收入口 SHALL 只提交到已有统一队列，不等待完整 Agent 轮次或出站投递。系统 SHALL 移除 wait_result 布尔调用模式；需要 Agent 操作结果的 Web 接口 SHALL 保持自身响应适配。

#### Scenario: 模型正在执行

- **WHEN** 实例的 Agent 对话仍在处理上一条消息，又收到新消息
- **THEN** 接收入口提交新消息到队列后返回
- **AND** 消费者在已有调度规则下处理新消息，不在 SDK 回调内执行模型

### Requirement: 高优先级指令独立分流

系统 SHALL 使用已有命令分类将高优先级指令交给指令处理通道，保留停止、Agent 安全边界和会话切换屏障，不能把所有输入当作普通文本依次等待模型完成。

#### Scenario: 运行中收到停止指令

- **WHEN** 实例绑定的对话正在运行，实例收到 /stop
- **THEN** 停止指令进入高优先级处理通道并调用 Agent 取消
- **AND** 不等待当前模型轮次先正常完成

#### Scenario: 显式切换对话

- **WHEN** 切换对话指令按已有顺序屏障执行成功
- **THEN** 渠道实例的当前绑定更新为指令结果的对话
- **AND** 失败的切换不改变绑定

#### Scenario: resume 修改实例绑定

- **WHEN** 实例收到 /resume 加一个存在的 Agent 对话 ID
- **THEN** 校验成功后实例绑定改为该对话
- **AND** 不要求该对话曾属于当前平台对端或实例

#### Scenario: resume 目标不存在

- **WHEN** 实例收到 /resume 加一个不存在的 Agent 对话 ID
- **THEN** 系统报告目标不存在且保留当前绑定

### Requirement: Agent 出站时确认渠道绑定

系统 SHALL 在渠道外发前核对实例当前仍拥有输出所属的 Agent 对话，并通过该实例的可信目标调用已有平台发送 API。系统 SHALL NOT 将旧输出转投到改绑后的其他对话。

#### Scenario: 处理期间解除或更换绑定

- **WHEN** Agent 产生对话 A 的输出，而来源实例已经解除绑定或改绑对话 B
- **THEN** 系统不通过该实例把 A 的输出作为 B 的回复发送
- **AND** 明确记录绑定不匹配导致的未发送结果

### Requirement: Workflow 复用已有通知发送

单向渠道 SHALL 仅用于现有 Workflow 通知路径。Workflow 向双向渠道发送通知时 SHALL 复用其已有适配器和平台发送 API，保留发送快照与投递确认，无须 Agent 对话绑定。

#### Scenario: 单向渠道通知

- **WHEN** Workflow 通过 Email 或 file 发出通知
- **THEN** 系统沿用已有发送及等待投递结果的路径
- **AND** 不创建或绑定 Agent 对话

#### Scenario: 双向渠道作为通知目标

- **WHEN** Workflow 选择一个尚未绑定 Agent 对话的 Telegram 实例作为通知目标
- **THEN** 系统使用本次通知快照调用其已有发送 API
- **AND** 不启动 Agent 接收或增加另一套发送实现

### Requirement: 存量对话不自动变为实例默认绑定

系统 SHALL 保留旧平台对端的对话与请求证据，不自动从多个旧对话中选一个作为实例绑定。

#### Scenario: 升级前存在多个对端对话

- **WHEN** 一个实例的旧记录包含多个好友分别对应的 Agent 对话
- **THEN** 原对话及去重历史仍可读取
- **AND** 当前实例绑定由用户显式选择，不能按最近一次消息猜测
