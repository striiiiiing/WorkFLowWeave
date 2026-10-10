# 设计：轻量第三方微信通知服务

## Scope

依据本变更 proposal 的上游源码证据和用户指定迁移要求，以 WeClawBot-API 现有公开 HTTP 能力为边界，采用独立第三方服务而不是安装完整 OpenClaw 宿主。用户未要求本轮维护第三方 fork；网页扫码和 Agent 双向对话不虚构接口、不保留失效按钮。后续可参考用户提供的腾讯云文章实现自有接入。

## Decisions

1. 保留渠道能力名称 wechat_openclaw，避免资源引用改名；实现改为 HTTP notification-only，schema 改为 api_url、bot_id、api_token。旧 account_id/state_dir/command/target_id 必须重新配置，明确报错而非静默迁移。bot_id 是第三方原始账号 ID，例如 xxx@im.bot，不是原宿主规范化 ID。
2. 使用核心已依赖的 httpx.AsyncClient，POST /bots/{bot_id}/messages，text 在 JSON body，api_token 仅作为 Authorization: Bearer header；禁止 token query/body、自动重试、跟随重定向。服务地址仅允许 HTTP/HTTPS，拒绝 URL 内凭据、query、fragment；bot_id 编码为单个路径段，拒绝斜杠和路径跳转。
3. api_token 沿用 Credential schema 和现有加密/环境变量解析器，不硬编码、不向浏览器返回解析值。外部响应只保留 HTTP/code 状态等非秘密信息，不透传可能含凭据和消息的第三方 error 文本。
4. 成功须同时满足 HTTP 200 和 JSON 整数 code=200。明确 400/401/403/404/405/422 请求拒绝为未送达；5xx、超时、断链、非法响应/重定向为结果不确定，避免发送后的无确认状态误报成功。取消传播，无自动重复发送。
5. 不提供 target_id/workflow 路由覆盖：上游仅向服务保存的 ilink_user_id 发送。拒绝不支持的覆盖参数。只声明 notification，不提供 Agent 接收、reply 或 start_login。
6. 前端保留微信专用区域，但改为始终可见的第三方风险提示和终端登录说明。提示社区项目非腾讯官方、消息/凭据经服务处理、可信部署、HTTPS、auth.json/API Token 保密、平台可用性/账号风险及 10 条 context_token 限制。不增加确认门槛。
7. 删除旧微信 Node bridge、网页登录脚本、Node manifest/lock 及专用前端轮询；没有其它插件使用的通用登录 API/注册扩展也删除，避免没有使用者的第二套登录基础设施。Docker 不再安装或复制微信 node_modules，不因本变更改动其它部署方案。

## Defaults

- api_url 不给隐式默认值：本机部署可填写 http://127.0.0.1:26322；Docker 中此地址指后端容器自己，应填写可达服务地址，例如 http://weclawbot-api:26322。端口依据上游 startAPIServer/README。
- 超时沿用渠道的既有 timeout 与 remaining_delivery_time；不增加独立预算。HTTP client 常驻复用连接，关闭由 ChannelManager 生命周期负责。
- 第三方服务用户自行部署并维护，LogAgent 不下载或自动启动未获指令的第三方二进制。约 10 MB 为上游 README 声称，不能作为本地实测。

## Validation

真实本地 HTTP 回环服务核对路径、Bearer 头、JSON、拒绝/超时/断链/错误结构与脱敏；凭据解析失败和旧配置必须显式失败。注册测试确认 notification-only，前端单测和浏览器 smoke 验证风险、终端登录说明以及桌面/移动显示。后端命令硬超时 60 秒。没有真实用户扫码/服务账号授权时，不向个人微信发送测试消息。
