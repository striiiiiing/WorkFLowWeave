# WorkFLowWeave Plugins

默认通知适配器位于包内 `workflowweave/plugins/channel/<id>`，每个包包含 `plugin.json`、注册入口和实现。
核心仅装配 Web 渠道，包内适配器与用户导入插件由同一个注册器发现。
采集来源使用 MCP/CLI，测试用本地双向渠道保存在 `tests/fixtures`。

| 插件 ID | 能力 | 用途 |
| --- | --- | --- |
| email | notification | SMTP Workflow 通知 |
| file | notification | logging 文件追加记录 |
| qq | notification, conversation | QQ 官方 Bot SDK |
| wechat_openclaw | notification, conversation | 微信 OpenClaw SDK bridge；须用户先发消息，且不建议单向通知 |
| feishu | notification, conversation | 飞书 SDK |
| telegram | notification, conversation | Telegram SDK |

每个双向渠道实例可绑定一个 Agent 对话；绑定后的对话仍可通过 Web 查看。

微信只能在用户先发消息建立上下文后自动回复，每个 `context_token` 最多回复 10 条消息，因此不建议把微信配置为单向 Workflow 通知。
旧文件通知资源的 `channel="mock"` 在读取持久化资源时迁移为 `file`。

内置插件和用户插件共用唯一的启停文件 `plugin_dir/config.json`，例如：

```json
{
  "channel": {
    "email": {"enabled": false},
    "file": {"enabled": true}
  }
}
```

`plugin_dir` 只用于用户导入的插件；同 ID 用户插件不能覆盖内置插件。包内插件根可通过
`builtin_plugin_dir` 指向另一目录，默认值为包内 `workflowweave/plugins`。Docker 部署可将
`plugin_dir` 单独挂载，内置插件保持在镜像或由 `builtin_plugin_dir` 指向独立挂载。
详细 SDK、凭据与微信登录说明见 [渠道说明](channel/README.md)，容器启动见
[Docker 文档](../../../docs/docker.md)。
