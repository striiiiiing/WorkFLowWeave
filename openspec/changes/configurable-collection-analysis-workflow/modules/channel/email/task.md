# Email 通知渠道任务

状态：实现、主代理 code/spec 审查与全部验证完成。依据 [Email 设计](./design.md)、[网关设计](../design.md)。旧任务基线 `4dfa8d0`；新增常驻实例要求，SMTP 接受语义不变。依赖：Channel 网关、配置凭据。

- [x] 声明 host/port/sender/recipient/tls/username/password，未知字段及 CR/LF 拒绝、单收件人、认证字段成对；tls 默认 starttls，依据 Email design。校验不连接远端。
- [x] 使用异步 SMTP 客户端，常驻实例按需连接并串行提交；TLS 模式严格执行，UTF-8 text/plain MIME 使用通知原始标题正文。后续独立 send 可重建断开的连接，同一次 send 不重连补发。
- [x] DATA 后肯定接受才 success；受理后响应丢失/取消为 delivery_uncertain，连接/认证/收件人明确拒绝为失败；清理失败不推翻已接受事实。stop 按生命周期有界释放，凭据与服务原始错误不泄漏。
- [x] 注册内置 email 类型，声明直接依赖；本地 SMTP 服务验证实际 MIME、提交次数、拒绝、TLS、DATA 后断连及超时（每测试命令60秒），lint、构建、本地邮件投递烟测。

## 实现决策与审查（2026-09-17）

- EmailChannelType 由 builtin_channels() 导出供 Lifecycle 显式注入，配置注册仍归 PluginRegistry；业务适配器不扫描插件。options JSON Schema 包含说明、单邮箱约束、拒绝 CR/LF 与未知字段；password 使用公共 Credential schema 和 x-logagent-credential 注解，username/password 成对。默认 starttls 直接依据 Email design；没有隐式 TLS 降级。
- aiosmtplib 声明为直接依赖。start 只构造客户端；send 按需连接及认证，同一实例发送串行。网络阶段采用 ChannelConfig.timeout，整个调用也有总时限；不做内部重试，已断开的连接只在后续独立 send 重新建立。
- 分别调用 MAIL、RCPT、DATA，DATA 返回肯定接受才成功；认证、收件人、明确 DATA 拒绝均为确定失败，DATA 后断连或等待响应超时为不确定投递。原始服务响应不进入错误信息，诊断保留阶段、异常类型和 SMTP 数字响应码。
- MIME 为 UTF-8 text/plain；编码原始 UTF-8 字节以保留正文换行和末尾内容，标题由标准 MIME 库编码，拒绝头注入。Message-ID 从 session/output/channel ID 稳定散列产生，仅供关联，不能据此声称 SMTP 去重。
- stop 独立幂等、有界，QUIT/关闭失败作为清理错误报告，不更改既有发送回执。默认清理预算 5 秒与 Channel 本地资源释放预算一致，发送预算不被此值替代。
- 主代理审查并补充“取消排队发送不能关闭活动事务所用连接”的回归；只有获得发送锁的调用才有权关闭该 SMTP 连接。proposal/design 未修改。

## 验证

- 本地 TCP SMTP 专项 `27 passed / 1.45s / exit 0`。检查实际 MIME/正文完全一致、稳定关联、连接复用、认证与收件人拒绝、STARTTLS 不支持、implicit TLS 真实握手错误、DATA 后断开及超时、取消、排队取消隔离、缺少凭据解析器、标题注入、内置注册及凭据规范化。
- 全套回归 `timeout 60s uv run pytest -q`：`519 passed / 33.73s / exit 0`（langgraph 弃用 warning 为既有噪声）。`uv run ruff check src/logagent/channel tests/test_email_channel.py` 全通过，`uv build` 生成 sdist/wheel 成功。
- 本地 SMTP 端到端烟测走真实 ChannelManager 路径：`receipt.status == "success"`、DATA 恰好提交一次、`manager.stop()` 正常收尾，exit 0。
- 全部 SMTP 测试只连接本机回环测试服务，未向外部邮箱发信。
- 预算共享修补后全套 520 passed，33.75 秒，exit 0；Ruff、uv build、git diff --check 通过。常驻实例复用时的时限取自本次调用，回归见 `test_reused_connection_obeys_current_snapshot_timeout`。
