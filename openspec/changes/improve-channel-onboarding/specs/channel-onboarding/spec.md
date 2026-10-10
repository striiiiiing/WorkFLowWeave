## ADDED Requirements

### Requirement: 频道参数提供可操作的配置说明

系统 SHALL 在 Email 各项备注提供 Gmail 示例，说明 SMTP 信息获取位置、主机格式、端口差异、发件人/收件人及授权码；SHALL 保持已保存字段兼容。系统 SHALL 明示 QQ 首次互动要求及微信每个 context_token 最多回复 10 条消息，并提供真实可用的 file 路径示例。

#### Scenario: 配置 Email 与文件渠道

- **WHEN** 用户选择 Email 或 file
- **THEN** Email 显示授权码及各项 Gmail 备注，file 显示 logs/notifications.log 相对 data_dir 的解释

### Requirement: 微信可在网页内直接扫码登录

系统 SHALL 在创建或编辑微信渠道时提供二维码 PNG 与链接，复用官方 SDK 登录并将 Token 保存至本地账号文件，成功后只回填账号 ID 与有效配置。

#### Scenario: 扫码确认成功

- **WHEN** 用户点击扫码登录并用微信扫码确认
- **THEN** 网页显示二维码与链接，登录完成后显示成功并回填 account_id，API 和资源文件不包含 Token

#### Scenario: 平台要求数字确认或刷新二维码

- **WHEN** 官方 SDK 要求输入手机数字或刷新过期二维码
- **THEN** 网页显示数字输入或新的二维码，继续同一官方登录流程

#### Scenario: 登录被取消或失败

- **WHEN** 用户取消、关闭编辑页、改变登录配置，或依赖缺失、超时、账号文件保存失败
- **THEN** 登录进程被回收，失败显式显示，过期响应不回填账号，不伪造成功

#### Scenario: 同一状态目录同时登录

- **WHEN** 另一个页面对相同状态目录发起登录
- **THEN** 系统明确报告进行中会话冲突，不并发写入同一账号存储
