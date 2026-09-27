# Agent 双向渠道

现有 ChannelManager 仅发送 Workflow 通知，Agent 命令解析位于 HTTP 路由，无法将 QQ 与前端接到同一入口。

本次按用户要求新增双向渠道：Web、QQ 官方机器人、可测试的本地渠道共用 Agent 命令与事件边界。双向接收仅绑定 Agent；同一适配器提供 notification/send 时可独立供 Workflow 等模块单向发送。沿用现有插件发现、资源配置、凭据、常驻实例和发送回执。
