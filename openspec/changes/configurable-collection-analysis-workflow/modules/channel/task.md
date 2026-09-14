元信息
- 关联规范：[Channel 网关设计](./design.md)、[总体设计](../../design.md)、[数据模型 §2.4、§4.3、§6](../../contracts/data-models.md)、[模块接口 §5、§9](../../contracts/module-interfaces.md)。
- 任务总数：5。
- 预计执行时间：人工工作量约 4 小时 30 分钟；不含前置模块及 email、mock 子模块工作量。
- 执行状态：待执行计划。本轮先实现 collection，本文件仅描述 Channel 后续实现任务。
- 执行策略：按依赖 DAG 执行；Task 1 → Task 2 → Task 3 → Task 4 → Task 5。email、mock 在取得 Task 1 的契约后可独立推进；Task 5 等待两种适配器的验收产物。

# Task 1: 建立渠道数据模型与实例协议

描述：实现或复用 ChannelConfig、Notification、DeliveryResult、ChannelType、NotificationChannel 和只读注册表消费协议，固定跨模块语义；预计 45 分钟。

输入：Channel 数据与方法契约；已有公共基础类型、错误结构和凭据模型。

输出：渠道公共模型、实例工厂及 start/send/stop 协议、供插件与网关共用的声明类型。

依赖：contracts 模块提供的公共基础类型、ErrorInfo、Credential 及渠道/凭据协议；仅依赖这些基础产物，不等待 config 模块的资源 CRUD 或完整插件发现。

验收标准：
- ChannelConfig 严格检查公共字段，timeout 默认 30 秒并拒绝布尔值、非有限数、非正数及数字字符串，enabled 默认 True。
- Notification 保留 session_id、output_id、title、text 和可序列化 metadata；未知公共字段被拒绝。
- DeliveryResult 仅接受 success/failed/timeout/skipped，attempts 仅为本次调用的 0 或 1；成功和跳过不携带错误。
- 平台实例通过工厂绑定配置和 CredentialManager，协议无需引入接收循环、会话缓存或复杂继承体系。

# Task 2: 实现能力查询与无副作用配置校验

描述：让 ChannelManager 消费配置模块发布的只读 channelRegister，生成能力描述并执行公共及平台选项校验；预计 45 分钟。

输入：渠道契约、只读 channelRegister、平台 options_schema 和 ChannelConfig。

输出：ChannelManager.describe/validate、字段路径明确的脱敏校验错误。

依赖：Task 1；contracts 模块的 schema 校验基础；config 模块的只读 channelRegister 发布能力。

验收标准：
- describe 返回注册表实际能力及 schema，多个类型和同类型多个实例可共存；返回对象不能反向修改注册结果。
- 缺失类型、非 notification 能力和无效 options 均返回可识别错误及可修正字段路径。
- validate 不解析凭据、不构造运行实例、不连接远端、不创建文件或发送测试通知。
- Manager 不扫描插件目录、不导入入口、不另建可写注册表，也不改动调用方的配置。

# Task 3: 实现单条发送与回执协调器

描述：依据传入快照配置创建短生命周期实例，组织准备、启动、一次发送和清理，统一平台异常与回执；预计 75 分钟。

输入：已固定的 ChannelConfig、Notification、只读注册能力和凭据解析服务。

输出：ChannelManager.send 的单条发送与回执协调器、平台失败到 ErrorInfo 的映射。

依赖：Task 2；config 模块的 CredentialManager.resolve 及可隔离的配置快照产物。

验收标准：
- enabled=False 时直接返回 skipped/attempts=0，工厂、凭据解析、start/send/stop 均未调用。
- 类型缺失、凭据或启动失败产生 failed/attempts=0；进入插件 send 后 attempts=1，且每次调用最多进入一次。
- 同一 channel_id 的旧快照和新配置创建不同实例，目标取自各自传入的配置；Notification.text/metadata 不能覆盖收件人、路径或凭据。
- 平台明确接受返回 success；明确拒绝返回 failed；所有回执保留原 channel_id 和 output_id。
- 不创建发送队列、缓存、重试循环或后台发送任务；平台私有异常不要求 Workflow 自行解析。

# Task 4: 完成总超时、取消与有界关闭

描述：为整个准备、启动和发送过程实施总时限，保证取消和关闭时有界清理并保留真实接收事实；预计 60 分钟。

输入：单条发送协调器、可控制启动/发送/清理阶段的适配器替身。

输出：有界取消与关闭实现、ChannelManager.stop、可供 Workflow 处理的发送阶段与接收信息。

依赖：Task 3。

验收标准：
- 总 timeout 覆盖准备、启动和发送，不为各阶段重置完整预算；超时回执的 attempts 与实际是否进入 send 一致。
- 已确认接受后 stop 失败仍保留 success，清理诊断单独记录且不包含凭据或通知正文。
- 可能已被接收但未确认的失败/超时包含 error.details.delivery_uncertain=True，且不启动补发。
- 取消经有界清理后向调用方传播，并携带是否进入 send、是否明确接受的信息；不增加 cancelled 投递状态。
- Manager.stop 等待当前调用完成受控清理；重复关闭不重复投递或遗留本模块拥有的资源。

# Task 5: 验证内置渠道接入与网关边界

描述：将 email、mock 声明通过配置模块接入，在离线环境验证网关和平台适配器协作，并提供调用示例；预计 45 分钟。

输入：网关完整实现、内置 email/mock 适配器及其测试结果、配置模块注册能力。

输出：网关集成验收用例、单条通知调用示例及验证记录。

依赖：Task 4；email 模块的 SMTP 适配器及协议验收产物；mock 模块的 JSON Lines 适配器及并发验收产物；config 模块的内置声明注册与只读 channelRegister 发布。

验收标准：
- 配置模块注册 email 和 mock 后，网关查询到同一份真实能力说明和 schema，且无第二套字段清单。
- 本地 SMTP 测试服务和临时文件目标分别完成一次通知，网关回执与实际提交次数、文件记录数一致。
- 两个目标由测试调用方按顺序逐个 await；首个失败不抹去第二个结果，网关不替调用方改变顺序或决定部分结果策略。
- 配置更新、禁用、总超时、取消、接收不确定性和清理失败的回归用例通过。
- 验收不要求完整 Workflow 实现；网关本身不读取历史或保存运行状态。
