# LogAgent Plugins

通知适配器位于 `plugins/channel/<id>`，每个包包含 `plugin.json`、注册入口和实现。
核心仅装配 Web 渠道，具体平台由统一注册器发现。Collector 无预置实现或资源；
新建采集来源使用 MCP/CLI，测试用 Collector 和本地双向渠道保存在 `tests/fixtures`。

| 插件 ID | 能力 | 用途 |
| --- | --- | --- |
| email | notification | SMTP Workflow 通知 |
| file | notification | logging 文件追加记录 |
| qq | notification, conversation | QQ 官方 Bot SDK |
| wechat_openclaw | notification, conversation | 微信 OpenClaw SDK bridge |
| feishu | notification, conversation | 飞书 SDK |
| telegram | notification, conversation | Telegram SDK |

每个双向渠道实例可绑定一个 Agent 对话；绑定后的对话仍可通过 Web 查看。
旧文件通知资源的 `channel="mock"` 在读取持久化资源时迁移为 `file`。

插件启停配置放在 `plugin_dir/config.json`，例如：

```json
{
  "channel": {
    "email": {"enabled": false},
    "file": {"enabled": true}
  }
}
```

部署到自定义 `plugin_dir` 时复制所需插件，保留 `channel/<id>` 分组结构；
空目录不会自动安装适配器。详细 SDK、凭据与微信登录说明见
[渠道说明](channel/README.md)，容器启动见 [Docker 文档](../docs/docker.md)。
