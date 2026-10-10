# 渠道 Secret 编辑契约与实现

依据：现有 `redesign-frontend-modules/design.md` §4 规定 Resources Model 保留 Credential 类型、资源编辑只负责配置；插件 `plugins/channel/{qq,feishu,telegram}/channel.py` 用 `x-workflowweave-credential` 标识凭据，Bot schema 将 App ID 与 Secret 声明为必填。原 `ChannelEditor` 把凭据从 `ParameterField` 排除交给独立控件，独立控件允许“暂不配置”，所以只有 App ID 也能提交 null，渠道启动时才在认证阶段失败。

用户 2026-10-06 明确要求：密码在前端编辑草稿中保留明文；带有 `secret` 名称或凭据注解的字段自动使用密码输入，默认圆点且可点击显示；JSON 编辑直接显示和编辑明文，并把行为写入契约。此任务不修改既有 proposal/design，新增行为只记录在本 task。

## 决策

- `ChannelEditor` 使用一份完整 `options` 草稿，普通表单和 JSON 模式不再分出第二份凭据状态；不新增 localStorage 等持久化。
- `ParameterValue` 对名称含 `secret`（不区分大小写）或带 `x-workflowweave-credential` 的字符串自动使用密码输入和 `show-password`；必填凭据字段默认启用。JSON 模式完整显示草稿中的明文，不排除字段、不替换星号、不静默保留用户删除的字段。
- 前端临时 schema 接受凭据字符串与原有 Credential/null 形状，并递归保留原有 `allOf`、引用和非凭据约束。提交前检查必填凭据；对标注 Credential 的明文字符串调用现有 `resourcesApi.protectCredential`，再用原始资源 schema 校验，最终 create/replace 只发送环境变量引用或加密 Credential。
- 保护或保存失败显示真实错误并保留当前草稿以便重试；不把明文写入日志或后端持久化。已有 env/encrypted 引用按真实 JSON 对象编辑，因为后端没有解密回读接口，前端不虚构其明文。

## 验收与验证

- [x] 只填写 QQ Bot App ID 时阻止创建；必填 Secret 为 null 或空字符串时阻止替换。
- [x] Secret 字段默认圆点、点击可显示；表单输入与 JSON 明文来回切换保持同一值。
- [x] JSON 中输入明文 Secret 后，保存前调用凭据保护；保护失败不调用资源保存接口。
- [x] SMTP 用户名/密码条件和普通 options schema 约束未被临时 schema 绕过。
- [x] `rtk proxy ./node_modules/.bin/vitest run tests/unit/resource-config.test.ts tests/unit/parameter-field.test.ts tests/unit/schema-validation.test.ts tests/unit/channel-conversation.test.ts tests/unit/provider-proxy.test.ts --maxWorkers=2`：5 个文件、36 项通过。
- [x] `rtk proxy npm run typecheck`：通过。
- [x] `rtk proxy npm run architecture:check`：200 个源文件、44 个 fixture 通过。
- [x] `rtk proxy npm run build`：Vue 类型检查与 Vite 生产构建通过，4220 个模块转换完成；仅有依赖包 Rollup 注释位置 warning。
- [x] 相关文件 Prettier check、`rtk proxy git diff --check`：通过。
