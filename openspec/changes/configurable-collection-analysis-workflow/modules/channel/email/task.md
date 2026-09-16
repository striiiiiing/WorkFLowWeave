# Email 通知渠道任务

状态：待执行。依据 [Email 设计](./design.md)、[网关设计](../design.md)。旧任务基线 `4dfa8d0`；新增常驻实例要求，SMTP 接受语义不变。依赖：Channel 网关、配置凭据。

- [ ] 声明 host/port/sender/recipient/tls/username/password，未知字段及 CR/LF 拒绝、单收件人、认证字段成对；tls 默认 starttls，依据 Email design。校验不连接远端。
- [ ] 使用异步 SMTP 客户端，常驻实例按需连接并串行提交；TLS 模式严格执行，UTF-8 text/plain MIME 使用通知原始标题正文。后续独立 send 可重建断开的连接，同一次 send 不重连补发。
- [ ] DATA 后肯定接受才 success；受理后响应丢失/取消为 delivery_uncertain，连接/认证/收件人明确拒绝为失败；清理失败不推翻已接受事实。stop 按生命周期有界释放，凭据与服务原始错误不泄漏。
- [ ] 注册内置 email 类型，声明直接依赖；本地 SMTP 服务验证实际 MIME、提交次数、拒绝、TLS、DATA 后断连及超时（每测试命令60秒），lint、构建、本地邮件投递烟测。
