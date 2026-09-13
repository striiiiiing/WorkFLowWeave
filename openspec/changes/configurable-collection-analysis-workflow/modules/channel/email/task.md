元信息
- 关联规范：[邮件渠道设计](./design.md)、[Channel 网关设计](../design.md)、[总体设计](../../../design.md)、[数据模型 §2.4、§2.5、§4.3](../../../contracts/data-models.md)、[模块接口 §5](../../../contracts/module-interfaces.md)。
- 任务总数：3。
- 预计执行时间：人工工作量约 3 小时；不含网关及配置模块工作量。
- 执行状态：待执行计划。本轮 collection 实现不包含邮件投递功能。
- 执行策略：Task 1 → Task 2 → Task 3；取得渠道契约后，可与 mock 适配器及网关协调器实现并发推进。

# Task 1: 定义邮件能力声明与选项校验

描述：声明 email 的 notification 能力，实现完整 options_schema 及地址、TLS、认证参数语义校验；预计 45 分钟。

输入：邮件 options 规范、ChannelType/ChannelConfig 契约和 Credential 模型。

输出：email 类型声明、平台选项模型和纯配置校验器。

依赖：公共契约中的 ChannelType/ChannelConfig、Credential 模型与 schema 校验基础；channel 模块的实例协议。

验收标准：
- schema 描述 host、port、sender、recipient、tls、username、password 的类型、默认值及含义，未知选项被拒绝。
- host 非空，port 为 1–65535 的整数，sender/recipient 各为单个邮箱地址且拒绝 CR/LF，tls 仅为 none/starttls/implicit。
- username/password 必须成对提供，password 只接受 Credential 或 null；不接受明文密码持久化配置。
- timeout 和 enabled 使用 ChannelConfig 公共字段，校验不发起 SMTP 连接、认证或凭据解析。

# Task 2: 实现一次 SMTP 提交及接收事实

描述：实现异步 SMTP 适配器，以快照目标构造 UTF-8 text/plain MIME，执行显式 TLS、可选认证和一次消息提交；预计 75 分钟。

输入：校验后的邮件配置、Notification、CredentialManager 和异步 SMTP 客户端。

输出：email 实例工厂、start/send/stop 实现、可供网关映射的 SMTP 失败与不确定性诊断。

依赖：Task 1；config 模块的 CredentialManager.resolve。依赖 channel 实例协议，不等待网关集成验收。

验收标准：
- From、To 和 SMTP 信封地址固定取自配置；Subject 和 text/plain 正文分别使用原 Notification.title/text，正文不插入额外实现信息。
- none、starttls、implicit 按配置执行，协商或认证失败明确报错，不静默降低 TLS 模式或改用其他凭据。
- send 最多提交一次消息，客户端的自动重试和断线重连补发关闭，网络操作有时限。
- 只有服务器明确接受完整 DATA 才报告成功；提交后响应丢失、超时或取消携带 delivery_uncertain 信息。
- stop 关闭连接；已知接受事实不会因断连清理错误消失，诊断不输出认证内容或正文。

# Task 3: 使用本地 SMTP 服务验收协议边界

描述：建立可控制返回码、断开点和延迟的本地 SMTP 测试服务，验收 MIME、调用次数及网关回执；预计 60 分钟。

输入：SMTP 适配器、网关发送与取消实现、本地可控 SMTP 服务及临时凭据替身。

输出：邮件协议验收用例与执行记录，供渠道网关集成任务使用。

依赖：Task 2；channel 模块的单条发送与回执协调器、有界取消与关闭实现。

验收标准：
- 实际接收的 MIME 可还原 Unicode 标题和多行正文，信封地址与配置一致，每次成功调用只收到一条消息。
- 连接失败、认证拒绝、收件人拒绝、TLS 错误产生可区分的失败诊断，实际提交次数符合每次最多一次的约束。
- 在 DATA 已提交后丢失响应或取消时，结果保留不确定性，服务未收到自动补发。
- 在准备阶段和 send 内分别注入超时，验证 attempts=0/1；已明确接受后的关闭失败仍保留成功事实。
- 全部验收使用本地服务或测试替身，不依赖真实邮箱、外部 SMTP 服务或持久化明文凭据。
