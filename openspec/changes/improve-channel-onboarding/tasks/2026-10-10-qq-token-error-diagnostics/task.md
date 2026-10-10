# QQ Token 拒绝诊断

## 依据与决策

- 用户报告 QQ Bot token 请求被平台拒绝；`artifacts/channel-real-20261009/conversation-final.json` 和 `qq-final-retest.json` 记录该资源 token 请求返回 HTTP 200、平台码 `100016`。
- 对 `data/resources.json` 中两个同 AppID 的 QQ 资源分别使用现有 `CredentialManager` 解密并请求官方 token endpoint：`qq_AIBot` 返回有效 token，`qq_9f8e2c4c-860d-4aa2-afec-5f9ee25fb0ef` 返回 `100016 invalid appid or secret`。诊断只记录资源 ID、平台码和 token 是否存在，不记录 Secret 或 token。
- 因另一个同 AppID 资源认证成功，endpoint、请求 JSON 结构和当前出站网络可用；失败资源保存的 Client Secret 无效或已重置是证据支持的根因。实现不替用户覆盖密钥。
- 在 QQ 插件错误边界把已观察到的 `100016` 映射为可操作的中文提示；其他平台码继续通过结构化 `details.platform_code` 保留。依据 `tests/channel/test_qq_sdk_contract.py` 中真实 token 请求契约及本次脱敏核验。
- 不修改 `improve-channel-onboarding/design.md`：首次连接、凭据所有权及平台适配契约均未变化，只细化已存在认证错误的诊断。

## 工作项

- [x] 为 `100016` 增加明确的 AppID / Client Secret 提示，并保留平台码。
- [x] 在 QQ 渠道文档记录重置 Secret 后需重新录入，且资源可保存不同 Secret。
- [x] 验证 QQ token 契约测试、Ruff 和差异格式。

## 真实核验

- 报错资源：HTTP 200，code `100016`，message `invalid appid or secret`，无 `access_token`。
- 同 AppID 的 `qq_AIBot`：HTTP 200，返回 `access_token` 和有效期。
- 结论：平台拒绝的是该资源保存的 Client Secret；未改写资源或凭据。
