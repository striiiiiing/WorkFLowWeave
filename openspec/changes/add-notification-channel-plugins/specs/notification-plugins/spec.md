# 通知插件能力增量

> 2026-10-04 用户确认；实现验收状态见 tasks.md。

## ADDED Requirements

### Requirement: 具体通知渠道属于插件

系统 SHALL 将 Email、文件、QQ、微信“小龙虾”、飞书和 Telegram 的具体适配器放在 plugins/channel/<id>/ 的独立 channel 插件中；核心渠道层 SHALL 只依赖通用协议、注册器、Manager、队列和平台无关模型。

#### Scenario: 缺少一个平台 SDK

- **WHEN** 某个可选平台 SDK 未安装
- **THEN** 只有对应插件报告缺失依赖或不可用诊断
- **AND** 其他已安装插件和核心 Manager 仍可发现、启动和发送

#### Scenario: 插件注册

- **WHEN** 插件通过 `plugin.json` 和 `main.py` 被发现
- **THEN** 它通过现有 `ChannelPluginApi` 注册 channel type
- **AND** 插件不创建第二个 Manager、不直接调用 Agent 模型循环

### Requirement: 渠道能力矩阵

系统 SHALL 提供以下能力：Email 和文件仅声明 `notification`；QQ、微信“小龙虾”、飞书和 Telegram 同时声明 `notification` 与 `conversation`。

#### Scenario: 单向渠道关闭 Agent 接收

- **WHEN** Workflow 向 Email 或文件渠道调用 `send`
- **THEN** 通知按本次配置快照发送或记录
- **AND** 不创建 Agent 会话、不进入入站队列、不启动接收循环

#### Scenario: 双向渠道输入

- **WHEN** QQ、微信、飞书或 Telegram 收到一条平台消息
- **THEN** 插件验证来源和平台路由后把规范化输入交给唯一 `ChannelManager`
- **AND** Agent 回复使用同一条可信平台路由

### Requirement: 官方 SDK 优先

QQ SHALL 使用腾讯 `qq-botpy`；飞书 SHALL 使用 `lark-oapi`；Telegram SHALL 使用 `python-telegram-bot`；Email SHALL 使用 `aiosmtplib`。插件 SHALL NOT 在核心层重复实现对应平台的鉴权、事件或消息协议。

#### Scenario: SDK 回调进入统一队列

- **WHEN** 官方 SDK 调用 QQ、飞书或 Telegram 的入站回调
- **THEN** 回调只负责归一化消息并等待 Manager 的实际入队结果
- **AND** 插件不在回调中直接执行 Agent 或 Workflow

### Requirement: Email SMTP 单向投递

Email 插件 SHALL 只支持 SMTP 出站。凭据 SHALL 通过 `CredentialResolver` 取得；DATA 被服务器明确接受才可报告成功；响应在 DATA 后丢失时 SHALL 报告投递不确定且不得隐式重试。

#### Scenario: SMTP 成功

- **WHEN** SMTP 连接、认证、MAIL、RCPT 和 DATA 均获得成功响应
- **THEN** Email 渠道返回一次成功投递结果

#### Scenario: DATA 响应不确定

- **WHEN** 客户端在 DATA 阶段失去连接且无法判断服务器是否接受邮件
- **THEN** 渠道报告不确定状态
- **AND** 不自动重新发送同一通知

#### Scenario: Email 入站

- **WHEN** 用户为 Email 资源设置 `agent_enabled=true`
- **THEN** 资源校验或生命周期启动明确拒绝该组合
- **AND** 系统不启动 IMAP、POP 或其他收信任务

### Requirement: 本地文件通知记录

文件插件 SHALL 将每次通知通过标准库 logging 作为一条 UTF-8 可读日志记录追加到配置文件；写入并 `flush` 成功后才报告成功。路径 SHALL 遵循 `data_dir` 相对路径规则，并 SHALL 串行化同一文件的并发写入。

#### Scenario: 一条通知对应一条记录

- **WHEN** 文件渠道收到一条包含换行、引号或 metadata 的通知
- **THEN** 文件追加包含时间、来源标识、标题和正文的日志记录
- **AND** 原始 `session_id`、`output_id`、标题、正文可被读取

#### Scenario: 文件写入失败

- **WHEN** 文件打开、写入、flush 失败
- **THEN** 渠道返回明确的失败或不确定投递结果
- **AND** 不伪造成功或静默丢弃记录

### Requirement: 微信小龙虾使用受支持桥接

微信“小龙虾”插件 SHALL 在用户确认其指代 OpenClaw Weixin 后，通过受支持的 OpenClaw/Tencent iLink sidecar 或 bridge 接入；WorkFLowWeave SHALL NOT 在本项目内重写 iLink 协议。

#### Scenario: 微信桥接不可用

- **WHEN** sidecar 未安装、未登录或平台响应不确定
- **THEN** 渠道返回明确的配置、认证或投递错误
- **AND** 不静默切换到未声明的微信协议实现

### Requirement: 新资源不含采集器预配置

创建新的资源文档时，系统 SHALL 不自动创建 sources、setters、旧 default_file 或 mock 通知资源，且 SHALL 删除配送的 mock/logs/history Collector 实现及其默认注册。已有用户资源 SHALL 保持不变，除非用户确认并执行显式迁移。

#### Scenario: 新建资源文档

- **WHEN** 生命周期首次创建资源文件
- **THEN** 采集器和旧文件渠道集合为空
- **AND** 用户必须显式选择并配置通知或采集来源

#### Scenario: 已有旧文件资源

- **WHEN** 已有资源包含旧 `mock` 文件渠道
- **THEN** 系统按确认后的迁移规则保留其路径和资源身份
- **AND** 迁移失败时报告原因，不自动回退到核心实现

### Requirement: 分组插件发现

系统 SHALL 在同一注册器中发现 plugins/channel/<plugin>，保持根目录自定义插件兼容；分组目录 SHALL NOT 作为缺少清单的插件报错，重复 ID SHALL 使用既有冲突诊断。

#### Scenario: 分组目录加载

- **WHEN** 插件根目录包含六个 channel 子插件
- **THEN** 注册器发现具体通知插件且不注册任何默认 Collector
- **AND** channel 分组目录不产生清单缺失错误
