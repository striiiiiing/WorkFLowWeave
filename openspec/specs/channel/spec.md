# channel

## Purpose

说明统一渠道管理、有序入站、取消、受理回执、实例绑定和原路回复，区分平台会话与 Agent 会话以及 Workflow 单向通知。未完成的实现与验收仍由所属活动变更管理，历史验证不能替代当前版本回归。

## Requirements

### Requirement: 统一双向渠道管理
系统 SHALL 由唯一 ChannelManager 管理 Web、QQ 和 test 的对话输入、队列消费及渠道生命周期；双向输入 SHALL 仅绑定 Agent。

#### Scenario: 三种输入同一处理链路
- **WHEN** 前端、QQ 或测试渠道提交一条对话消息
- **THEN** 消息在真实入队后返回受理结果，由 Manager 的消费者调用渠道通用消费流程和注入的 Agent 处理端口
- **AND** HTTP 路由和适配器 SHALL NOT 绕过队列直接执行 Agent

#### Scenario: Workflow 作为上下文来源
- **WHEN** Agent 命令选择一个已有 Workflow 最终结果
- **THEN** 结果只用作 Agent 上下文，Workflow 不成为双向消费者且不会因此启动运行

### Requirement: 有序消费与独立取消
系统 SHALL 对同一平台对话的普通消息按受理顺序消费，等待活动轮次结束；stop SHALL 经独立取消通道执行。

#### Scenario: 连续消息与会话切换
- **WHEN** QQ/test 的同一绑定式对话中 A 正在执行，随后依次受理 B、new 和 C
- **THEN** 执行顺序为 A、B、new、C，C 进入新会话，B 不因忙碌而被丢弃

#### Scenario: Web 明确指定会话
- **WHEN** Web 创建或分支出新会话时还有已指明旧 session 的消息等待处理
- **THEN** 已受理消息仍属于旧 session，只有后续显式指定新 session 的请求进入新会话

#### Scenario: 停止发生在首次创建期间
- **WHEN** 首条消息正在创建或提交 Agent 会话，同时受理 stop
- **THEN** 首条消息在执行前中断或其实际启动的轮次被取消，stop 完成后不能再启动该旧消息
- **AND** stop 前此来源的待处理请求取得 interrupted 回执，stop 后的新消息可正常继续

#### Scenario: 重复停止
- **WHEN** 已完成的 stop 请求被重复投递
- **THEN** 返回原回执，不取消后来受理的消息

#### Scenario: 多来源操作同一 Agent 会话
- **WHEN** 不同渠道队列中的消息指向同一 Agent session
- **THEN** 普通消息等待原子准入，同一 session 至多有一个活动模型轮次，取消不会被等待准入的请求阻塞

#### Scenario: 安全边界命令
- **WHEN** append 或 compact 作用于活动轮次
- **THEN** Agent 在原有安全边界执行命令，渠道报告命令自身的结果，不创建虚假轮次或重复发送整个活动轮次的最终文本

#### Scenario: 命令先于等待中的普通消息
- **WHEN** A 正在执行、B 已排队，随后受理 append 或 compact，且此前没有尚未完成的会话切换屏障
- **THEN** 命令可先在 A 的安全边界生效，B 仍等待 A 结束后执行

### Requirement: 可查询的受理和处理结果
系统 SHALL 区分请求入队、Agent 执行结果和发送回执，并 SHALL NOT 将入队当成模型或投递成功。

#### Scenario: 排队阶段没有 turn ID
- **WHEN** 前端请求已入队但尚未被 Agent 准入
- **THEN** 后端保持 HTTP 等待，不向现有前端返回缺少 turn_id 的成功响应
- **AND** 真实准入后按原 TurnAccepted 结构响应，并从原事件日志重放输出

#### Scenario: 队列满载
- **WHEN** 输入队列没有容量
- **THEN** 请求明确被拒绝，Web/test 返回 429，QQ 记录拒绝并在平台允许时提示，不返回已受理成功

#### Scenario: Agent 已完成但回复失败
- **WHEN** Agent 轮次成功完成而平台拒绝回复或确认丢失
- **THEN** 请求保留实际完成结果，发送回执独立显示失败或不确定，系统不自动重发

### Requirement: 会话与原路回复隔离
系统 SHALL 固定可信来源身份、实例配置版本和原消息回复路由，持久化绑定，并校验外部恢复请求的既有会话归属。

#### Scenario: 重复和冲突输入
- **WHEN** 相同渠道及对话中收到已有 request_id
- **THEN** 相同内容返回原回执，不重复执行或发送；不同内容明确 request_conflict

#### Scenario: 会话或账号更新
- **WHEN** 处理开始后当前绑定或渠道账号发生变更
- **THEN** 在途回复仍使用原会话、实例和地址，未执行的旧账号输入被明确中断而不转投新账号

### Requirement: 前端事件统一渠道
前端对话写操作和事件流 SHALL 通过后端 WebChannel；Agent 原事件日志 SHALL 保持唯一对话正文来源。本变更 SHALL 不修改任何前端文件，后端 SHALL 兼容现有请求字段、响应结构、状态码及 SSE。

#### Scenario: 现有前端无需改造
- **WHEN** 现有前端发送原命令请求并订阅原事件 URL
- **THEN** 后端通过 Manager 的真实队列处理，并返回原 kind/result 和事件信封，不要求增加 conversation_key、轮询或事件类型处理

#### Scenario: SSE 延后订阅或重连
- **WHEN** 前端获得回执前 Agent 已输出事件，或 SSE 在处理中断开
- **THEN** 从原日志及游标恢复事件，断连不自动取消已受理请求

#### Scenario: 兼容旧对话接口
- **WHEN** 调用旧 Agent 对话写接口
- **THEN** 通过同一 WebChannel 的同一 session 队列入队并投影原结果，stop 可以处理另一路由受理的待执行消息，不保留直接执行 Agent 的旁路

### Requirement: 双向适配器的独立单向发送
支持 notification 的双向适配器 SHALL 允许 Workflow 等模块使用 send；该调用 SHALL 不进入输入队列、不调用 Agent、不依赖启用 Agent 接收。

#### Scenario: 关闭接收后发送
- **WHEN** 资源可发送且 agent_enabled=false，Workflow 调用 send
- **THEN** 按本次快照目标发送并返回 DeliveryResult，不创建 Agent 会话或启动接收循环

#### Scenario: 旧快照发送
- **WHEN** 资源配置已改变而活动 Workflow 持有旧快照
- **THEN** 使用旧快照实例与目标，保持既有单次发送预算和不自动重试语义

#### Scenario: 能力不支持
- **WHEN** 请求对只声明 conversation 能力的 Web 发送任意通知
- **THEN** 返回明确的能力不支持错误，不把通知伪装成 Agent 事件或要求改动前端

### Requirement: QQ 与可测试双向渠道
系统 SHALL 提供官方 QQ Bot 适配器，以及可注入消息、读取出站记录和查询回执的 test 渠道；两者 SHALL 经过真实 Manager 和 Agent 处理链路。

#### Scenario: 测试渠道闭环
- **WHEN** 测试注入普通消息并由 Agent 产生输出
- **THEN** 可按请求查询执行与投递状态，并在 outbox 读取固定原地址的回复
- **AND** 单向 send 另按配置目标记录，不触发 Agent 执行

#### Scenario: QQ 协议失败
- **WHEN** QQ 权限不足、回复窗口过期、发送被限流或确认缺失
- **THEN** 产生真实错误或送达不确定回执，不伪造成功或盲目重发

### Requirement: 可解释的生命周期与恢复
系统 SHALL 统一管理渠道启停与替换，保留清理失败引用，并 SHALL NOT 自动重放重启前结果未知的请求。

#### Scenario: 长轮次期间清理队列
- **WHEN** 队列为空但其消费者仍在等待 Agent 或发送结果
- **THEN** 不将其视为空闲，不取消该活动消费者

#### Scenario: 进程恢复
- **WHEN** 重启时存在未完成渠道请求
- **THEN** 通过现有 Agent 事实核对结果，确定未执行的标为 interrupted，无法判断的标为 outcome_unknown，不重新执行或发送

#### Scenario: 接收启动失败
- **WHEN** QQ 接收连接启动失败
- **THEN** 健康状态明确失败，其他渠道继续服务，独立单向发送按自身实际协议结果返回

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
