## ADDED Requirements

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
