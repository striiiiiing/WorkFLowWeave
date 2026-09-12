# Channel 网关模块设计（v0.1）

本文细化 [proposal.md](../../proposal.md) §2.1「channel 网关模块」及 [根 design.md](../../design.md) §4.1–§4.2。公共 `ChannelConfig`、`Notification`、`DeliveryResult` 使用 `logagent/models.py`，不在平台实现中复制模型。

## 1. 职责与边界

首版网关把已经形成的 Workflow 输出发送到配置的通知目标。它负责插件发现、实例配置校验、生命周期、平台协议、按序发送和每个目标的投递结果。内置平台为追加到文件的 `file` 和使用 SMTP 的 `email`。

Workflow 负责决定发送内容、输出顺序、目标顺序、是否发送部分分析结果，以及将投递记录写入 session。网关不启动 AI，不编辑分析正文，不改写 session 的分析成功状态，也不自行重新运行失败的 Workflow。

参考根目录三份 QwenPaw 解读中的实际边界：

| 参考 | 本模块采用的职责分离 |
| --- | --- |
| [通道注册表模块解读.md](../../../../../通道注册表模块解读.md) | 注册表只保存通道类、schema 和能力；不保存连接、队列和运行中实例 |
| [ChannelManager模块解读.md](../../../../../ChannelManager模块解读.md) | Manager 根据配置创建实例并协调生命周期；后台主动发送可以直接调用平台发送入口 |
| [BaseChannel模块解读.md](../../../../../BaseChannel模块解读.md) | 平台类承担协议和目标解释，公共基类只保留本项目当前需要的契约 |

QwenPaw 的输入队列、防抖、命令优先级和 Agent 请求消费有各自职责。首版只建立单向通知能力，不复制这些运行时，也不把“类可发现”当成“实例已启动”或“消息已送达”。

## 2. 子模块与依赖

| 计划文件 | 职责 |
| --- | --- |
| `logagent/channels/base.py` | `BaseChannel`、`NotificationChannel` 与能力声明 |
| `logagent/channels/registry.py` | 通道类型、schema、逐文件原子注册及发现诊断 |
| `logagent/channels/manager.py` | 实例管理、生命周期、有序投递、超时和有限重试 |
| `logagent/channels/file.py` | UTF-8 Markdown 追加及按真实目标文件共享的异步锁 |
| `logagent/channels/email.py` | SMTP 连接、TLS、认证、邮件构造与错误转换 |
| `tests/test_channels.py` | 顺序、部分失败、文件边界、SMTP、生命周期验收 |
| `tests/test_channel_plugins.py` | 发现、能力校验及文件注册原子性验收 |

网关依赖公共模型、已解析配置和日志；不依赖 Workflow 执行器或 ArchiveStore。文件和 SMTP 的阻塞操作交给工作线程，调用入口保持协程。

## 3. 技术选型（ADR）

暂不填写。

## 4. 公共接口与能力

```python
class BaseChannel:
    async def start(self): ...
    async def stop(self): ...

class NotificationChannel(BaseChannel):
    async def publish(self, notification): ...

class ChannelManager:
    def register(self, channel): ...
    def discover(self, path, plugin_config): ...
    def describe(self): ...
    def validate(self, config): ...
    async def start(self, configs=()): ...
    async def stop(self): ...
    async def publish(self, configs, notifications) -> list[DeliveryResult]: ...
```

`BaseChannel` 声明类型名称、能力和该类型的 `options` schema；实例持有已经校验的独立配置。它不要求 `receive()`，也不接受作为发送前置条件的 Agent 实例。平台的 `publish(notification)` 成功完成即返回，失败抛出带平台语义的错误，由 Manager 转换成 `DeliveryResult`。

`register(channel)` 接收具体通道类，拒绝抽象基类和重复类型名。首版 Workflow 目标必须声明 `notification` 能力并满足 `NotificationChannel` 契约。仅有后续控制或会话能力的声明不能通过首版通知配置校验。

`describe()` 返回独立能力描述，包括名称、能力集合、选项 schema 和插件归属；不输出解析后的环境变量值。`validate(config)` 只做 schema、能力及配置关系验证，不发送探测消息、不调用 SMTP。必需凭据是否存在可在实例启动/投递时检查，并返回可定位的错误。

### 4.1 配置及通知数据

| 对象 | 字段与语义 |
| --- | --- |
| `ChannelConfig` | `id/channel/options/timeout/retries/enabled`；`timeout` 为正有限秒数，`retries` 为首次失败后的额外尝试次数，非负整数 |
| `Notification` | `session_id/output_id/title/text/metadata`；正文已经由 Workflow 确定；每个输出有稳定 ID |
| `DeliveryResult` | `channel_id/output_id/status/attempts/error`；每个输出与目标组合独立返回，不用一个布尔值替代整批结果 |

`metadata` 可保留 `workflow_id`、输出阶段、分析任务等关联信息。网关复制后传给平台，插件不能修改原始通知影响其他目标。SMTP 收件人、文件路径等目标参数来自 Channel 配置，通知正文不能替换目标。

同一个 Workflow 的目标列表不重复使用同一个 Channel 实例 ID，同一通知批次中 `output_id` 不重复；不同实例可以使用相同平台。配置快照在本次发送期间固定，用户修改资源中的目标地址不会改变已经运行的 session。

### 4.2 投递状态

| `status` | 含义 | `attempts` |
| --- | --- | --- |
| `success` | 平台接口确认此次请求成功；SMTP 表示服务器接收，文件表示完整写入并 flush | 实际尝试次数，至少 1 |
| `failed` | 无效运行期配置、启动失败或平台明确失败；错误中保存可修正原因 | 实际尝试次数；发送前拒绝可为 0 |
| `timeout` | 本次尝试耗尽时限；不能把它当成已确认未送达 | 已开始的尝试次数 |
| `skipped` | 目标实例 `enabled=false` | 0，不实例化、不启动、不投递 |

成功和跳过的 `error` 为 `null`。错误使用 `LogAgentError` 的可序列化结构，至少包含代码与说明；例如 `CHANNEL_NOT_FOUND`、`CHANNEL_CONFIG_INVALID`、`CHANNEL_START_FAILED`、`CHANNEL_TIMEOUT`、`FILE_WRITE_FAILED`、`SMTP_AUTH_FAILED`。具体错误码不成为 Workflow 推进规则，Workflow 依赖状态及公共错误详情。

SMTP 超时或发送后断连可能无法确定服务器是否已接收。此时使用 `timeout/failed` 并在 `error.details.delivery_uncertain` 中明确标记，保留已知阶段信息，不宣称恰好投递一次。

## 5. 插件发现与配置隔离

启动扫描 `<plugin_dir>/channels/*.py`，按文件名排序；入口为 `register(registry)`。插件级 JSON 位于同名文件，例如 `channels/custom.py` 与 `channels/custom.json`，由发现模块读取并隔离错误；`discover(path, plugin_config)` 可接收按文件名分组的显式配置覆盖。插件通过 `registry.plugin_config` 获得本文件的独立设置，不增加注册入口的位置参数。

每个文件先获得临时注册表，在导入、配置、能力/schema 和重复名称全部通过后一次提交。任一声明失败都会撤销该文件的全部待注册项，其他文件照常发现。内置 `file/email` 不允许被插件覆盖；同一个文件注册多个不同通道类是合法用法。

未知目录、导入异常、损坏 JSON、缺少入口、重复名称及无效能力分别保留发现诊断。某个可选插件失败不影响内置平台和其他有效插件。发现诊断不等于一次投递结果；运行中引用缺失类型时仍需返回与该目标对应的失败记录。

原子性只保证注册表可见性。插件导入和声明不得启动网络连接或后台接收线程；Python 任意导入副作用不属于可回滚事务。首版只在启动时加载文件，不实现实例热替换。多能力注册只保留声明空间，首版不会为未实现的接收能力启动循环。

## 6. 实例与生命周期

管理器状态为 `created → running → stopping → stopped`。`start(configs)` 启用 Manager 并准备传入的启用配置；未预先出现的有效快照可在首次 `publish()` 时按需创建。重复启动不会重复连接；`stop()` 可重复调用，不因一个实例停止失败而跳过其余实例。

实例按 `(channel_id, 有效配置指纹)` 管理，而不是只按平台类型管理。配置指纹来自规范化后的配置值和环境变量名称，不包含解析后的秘密。同 ID 旧快照与新配置不能共享可变的收件人、路径或连接参数；运行中的旧快照不会被资源更新原地替换。

创建、启动、停止时对实例表使用短临界区；网络启动、SMTP 和文件 I/O 不能占用管理器的全局锁。并发首次使用同一实例只允许一个启动任务，其余调用等待该任务，并受各自发送期限约束。启动异常回收半初始化资源，状态可诊断。

每个实例的 `start()`、`stop()` 都必须有限完成。服务 lifespan 先停止接收新运行，取消或等待 Workflow，再关闭 Manager；Manager 进入 `stopping` 后拒绝新的投递。已启动实例按创建顺序的逆序关闭，单个 `stop()` 异常或超时被记录，继续关闭其余实例。

文件平台不长期持有文件句柄；SMTP 首版每次实际发送建立并关闭自己的连接，实例启动主要检查运行期配置和必要凭据。平台不需要常驻线程。第三方平台可以在实例内管理客户端，但必须在 `stop()` 中关闭并跟踪其后台任务。

## 7. 有序投递、重试与取消

### 7.1 输出和目标顺序

`publish(configs, notifications)` 的外层是通知声明顺序，内层是目标配置顺序。假设输出为 `summary/details`，目标为 `file/email`，调用与返回顺序均为：

```text
summary → file
summary → email
details → file
details → email
```

每个组合完成或耗尽重试后才推进下一个组合。某个目标失败、超时或被禁用，也返回对应结果；不得中断整批、删除此前成功记录或重新发送此前成功目标。空输出列表或空目标列表返回空结果。

该顺序保证作用于一次批次/Workflow，不承诺不同并发 session 的全局业务顺序。相同文件路径仍由文件级锁保护完整消息边界。Workflow 可以按照同一双层顺序逐项调用 `publish([config], [notification])`，每条回执立即写入 session，保证后续取消不会抹去已保存的成功投递。

### 7.2 尝试和超时

`timeout` 为每次实际投递尝试的总时限，包含必要的实例准备、文件锁等待或 SMTP 连接、握手、认证和发送。Manager 在进入本目标时开始计时，不把等待前一目标的时间算入本目标。SMTP socket 操作同时使用有限超时，防止线程在网络等待中永久占用。

最大尝试次数为 `1 + retries`。重试只适用于已确认尚未被目标接收的暂态错误；格式无效、缺失凭据、权限错误、认证失败、永久拒收不重试。退避采用可取消的短时异步等待，首版为 `min(2 ** (attempts - 1), 8)` 秒，测试使用可控时钟。

SMTP 已进入可能接收的阶段后断连、线程尚未退出的超时、部分收件人已接收等情况不自动重发整条通知，保留 `delivery_uncertain` 或已接收范围。`retries` 是额外尝试上限，不要求对永久错误或可能重复的结果用满次数。

### 7.3 取消、线程与恢复

取消向上层传播，不吞掉取消继续发送后续输出或目标。Workflow 逐条保存回执，恢复时跳过 `status=success` 的组合，基于原 session 的固定最终输出和目标配置补发失败组合。网关本身不读取存档、不维护第二份恢复队列。

工作线程不会因等待协程取消而立即停止。文件写入和 SMTP 操作都要跟踪实际 worker；超时后不得遗留无人持有的 Future、提前放开文件锁或同时启动同一消息的自动重试。文件锁持有任务等待实际写入结束后才释放；后续等锁调用仍受自己的期限约束。关闭时等待有界的在途操作，并记录未能确认完成的发送。

网络协议及“发送成功但 session 回执落盘前进程崩溃”存在确认窗口，无法单靠本模块做到恰好一次投递。平台可使用稳定的 `session_id/output_id` 生成关联标识，但不假设 SMTP 或普通文件会自动去重。显式恢复可能重复一个未确认结果，原错误必须保留供查询。

## 8. 内置 file 通知

`file` 是首版 Mock NotificationChannel，将通知追加到配置文件尾部。`options.path` 必填；配置中的相对路径以系统配置文件目录为基准解析，运行快照保存确定路径，不能随进程工作目录变化而改变投递目标。

文件内容为 UTF-8 Markdown，每条包含标题、session/output 标识和正文，以空行分隔。内容先在内存形成一整个消息块，再在目标文件的异步锁内追加并 flush。正文不重新分析或截断。一个文件中的完整消息不能与另一个同时发送的消息交错。

锁以规范化后的实际文件路径为键，而不是 Channel 实例 ID；两个不同实例指向同一个文件时共享同一把锁。该保证面向根设计规定的单服务进程，不宣称可协调独立多 worker 或外部写入者。

目标不存在时创建父目录和文件；目标为目录、不可写、非普通文件或写入失败返回明确错误。写入失败不能虚构成功或清空已有文件。进程/磁盘故障可能留下部分尾部字节，普通追加文件不提供跨系统故障的事务语义；通知存档仍保存完整原文用于排查或补发。

```json
{
  "id": "local_reports",
  "channel": "file",
  "options": {"path": "./data/notifications/reports.md"},
  "timeout": 5,
  "retries": 0,
  "enabled": true
}
```

## 9. 内置 email 通知

### 9.1 SMTP 配置

| `options` 字段 | 语义 |
| --- | --- |
| `host`、`port` | SMTP 服务器地址及端口，端口范围为 1–65535 |
| `security` | `none/starttls/ssl`，互斥单值；按配置明确使用明文、STARTTLS 或连接时 TLS |
| `sender`、`recipients` | 发件人和非空收件人列表；拒绝含 CR/LF 的头字段及无效地址 |
| `username_env`、`password_env` | 可选环境变量名称；需要认证时成对配置，发送时解析，不保存秘密值 |
| `subject_prefix` | 可选主题前缀，与 `Notification.title` 组成主题，禁止换行注入 |

使用标准邮件对象编码 Unicode 主题与 UTF-8 正文。首版正文为纯文本 MIME，保留原 Markdown 文本可读性，不要求 HTML 模板或附件。每个输出对应一次邮件提交，稳定关联信息可写入邮件头。

`security=starttls` 必须成功升级 TLS 后才认证或提交内容，升级失败不回退到明文；`ssl` 在连接时使用 TLS。使用默认可信证书验证，不能通过插件默认关闭校验。`none` 可用于本地测试 SMTP；服务不会替配置猜测 TLS 模式。

```json
{
  "id": "report_email",
  "channel": "email",
  "options": {
    "host": "smtp.example.invalid",
    "port": 587,
    "security": "starttls",
    "sender": "reports@example.invalid",
    "recipients": ["reader@example.invalid"],
    "username_env": "LOGAGENT_SMTP_USERNAME",
    "password_env": "LOGAGENT_SMTP_PASSWORD",
    "subject_prefix": "[LogAgent] "
  },
  "timeout": 30,
  "retries": 2,
  "enabled": true
}
```

示例仅使用保留域及凭据变量名。配置保存、`describe()`、日志、错误详情和 session 快照均不包含解析后的 SMTP 密码。

### 9.2 失败与成功含义

SMTP 工作线程处理连接、协商、认证、发送和关闭。正常成功表示服务器接受全部配置收件人的邮件提交，不等于收件箱最终送达。连接拒绝、认证失败、TLS 失败和服务器拒收转换为不同错误原因。

多个收件人中只有一部分接受时，该 Channel 的总体状态为 `failed`，详情保留已接收/被拒绝的范围及服务器原因；其他 Channel 结果不受影响。首版不自动对全体收件人重发。若在 DATA 之后连接异常导致确认未知，记录不确定性，不写成“确定未发送”。

所有邮件测试使用 mock transport 或本地 SMTP 测试服务，不主动向真实邮箱投递。通过测试替身核验连接模式、TLS 前置条件、环境变量解析、Unicode 编码、主题和正文及拒收处理。

## 10. 可验收测试矩阵

| 场景 | 输入或故障注入 | 可验收结果 |
| --- | --- | --- |
| 类型发现 | 空目录及一个合法通知插件 | `file/email` 和插件可描述；没有实际网络启动 |
| 注册原子性 | 文件先注册合法项，再声明重复名称 | 该文件零新增；其他文件照常可用 |
| 配置/能力校验 | 未知选项、未知平台、仅会话能力的类型 | 保存时得到字段错误，不接受半配置通知目标 |
| 多实例 | 同平台不同 ID/目标，旧快照与新配置并行 | 配置互不串用，旧 session 目标固定 |
| 禁用 | `enabled=false` | `skipped`、`attempts=0`，构造/启动/发送次数为 0 |
| 双层顺序 | 2 个输出、2 个目标、第一目标较慢 | 调用及返回保持输出后目标的声明顺序 |
| 部分失败 | file 成功、email 失败，另一个输出仍可送达 | 每个组合都有结果；此前成功不被丢弃或重发 |
| 有限重试 | 确定未接收的暂态失败后成功 | 尝试不超过 `1 + retries`，退避可取消 |
| 永久错误 | 缺失凭据、认证失败、文件权限拒绝 | 不用满无意义重试；错误不含秘密 |
| 送达不确定 | SMTP DATA 后断连或线程超时 | 标记不确定；不启动重叠自动重试 |
| 文件消息边界 | 两个实例并发向相同路径写入多条消息 | 原内容保留，每条消息连续完整，没有字节交错 |
| 文件故障 | 目录目标、非普通文件、写入中异常 | 明确失败；不清空旧数据，不谎报成功 |
| SMTP 模式 | none、STARTTLS、SSL 三个测试替身 | 按配置建连；STARTTLS 失败不降级发送 |
| SMTP 内容 | 中文标题/正文、多收件人、含换行头字段 | Unicode 正确；头注入拒绝；部分拒收可诊断 |
| 生命周期隔离 | 一个实例 start/stop 抛错或超时 | 其他实例可发送/关闭，Manager 全局锁不被长期占用 |
| 取消 | 当前目标等待中取消批次 | 不继续发送后续组合，实际 worker 被跟踪和清理 |
| 恢复协作 | 一次成功、一条失败后由 Workflow 恢复 | 成功组合不重复；失败组合使用原固定输出补发 |

模块测试不需要真实模型、真实邮箱或外部平台。Workflow 集成测试另外确认投递失败只影响通知状态和 session 汇总，已经完成的采集、分析及最终输出仍可查询。

## 11. 后续扩展位置

能力集合允许一个插件分别注册 `NotificationChannel`、后续 `ControlChannel` 和 `ConversationChannel` 实现。扩展时 Manager 继续负责实例与生命周期，协议类继续负责平台数据；接收、命令分派和会话队列另行设计，不增加首版必需运行环节。

会话路由将以 `(channel_id, conversation_id)` 隔离，Workflow 通知仅携带来源关联信息，不切换正在进行的对话。后续控制指令可调用内部应用入口，是否开启控制能力由实例配置明确表达；不会因为平台支持接收就默认允许系统配置操作。

健康监测可通过新增可选能力提供查询，但“实例存在”“启动完成”“平台连通”“某条通知送达”仍分别记录。平台幂等键和更精细的收件人补发可以后续扩展，首版不承诺双向 Agent、消息队列持久化、平台自动重连或恰好一次投递。
