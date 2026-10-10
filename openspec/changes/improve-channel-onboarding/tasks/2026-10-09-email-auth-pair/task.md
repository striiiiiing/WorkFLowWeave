# Email 授权码配对校验修复

依据：`../../design.md` 决策 6 和 `../../../add-notification-channel-plugins/design.md` §4.2；前端凭据编辑沿用 `../../../redesign-frontend-modules/tasks/2026-10-06-channel-credentials/task.md`。不修改 proposal/design。

根因：后端 email schema 在 username 缺失或 null 时使用 else 将 password 限制为 null；前端复用该条件，所以用户先填授权码会收到“此字段只能为空值”。

这是前后端共享 schema 契约的结构修复：删除 else 的空密码限制，改为双向条件要求认证用户名与凭据配对。无认证 SMTP 仍允许同时省略或置 null；不根据 sender 静默推断 username，因为 SMTP 用户名不一定等于发件人。持久化仍只接受 Credential，不允许明文。

前端凭据草稿继续递归转换 if/then 中的对象条件以接受明文，并要求明文至少 1 个字符，避免把空授权码发往加密接口。表单/JSON 与后端都复用插件规则，不新增 email 专用校验逻辑。授权码说明明确须同时填写认证用户名，无新增默认值。

验证：覆盖先填授权码且 username 缺失/null/空字符串、补齐用户名后加密保存、合法凭据引用、明文与孤立用户名拒绝、无认证 SMTP 发送；运行后端单测（硬超时 60 秒）、前端单测、类型检查、构建和最小 smoke。

验证结果：后端 email 单测 34 项、前端资源配置/schema 单测 16 项通过；vue-tsc、Ruff、Prettier、生产构建和 diff check 通过。后端首轮 SMTP recipient 测试受 0.1 秒预算影响失败，复跑整组通过。Tabbit 已检查用户实际 3000 页面和真实 email schema；用户重启后端后确认原报错消失。未验证真实邮箱投递。
