# 设计

用户已授权先记录 OpenSpec，再实现；飞书采用保持单聊的官方应用机器人协议。本变更继承 add-notification-channel-plugins、improve-channel-onboarding 的平台无关核心边界，并取代默认插件与用户插件共用目录的约定。

## 首次连接

1. 首次连接由唯一 ChannelManager 管理，适配器提供可选的地址到通知选项映射，核心不硬编码平台地址枚举。持久化目标仍使用渠道资源 options，不新增第二份路由真源。
2. 保存并开启渠道后，前端发起 POST /channels/{id}/connection，GET 同路径轮询本地状态，DELETE 同路径取消。状态为 idle、connecting、waiting_message、connected、failed、cancelled。响应仅含实例 ID、状态、说明、结构化错误和非秘密目标选项，Cache-Control: no-store。
3. 首条有效私聊消息用于连接，不交给 Agent；使用事件原地址和消息 ID 回复精确文字「成功连接」，验证发送回执后才保存目标并报告 connected。失败显式报告且不自动重发；重复消息不产生重复确认。
4. 单向实例临时启用同一适配器的接收能力，结束、取消、失败、超时或应用关闭时回收；双向实例复用已有接收实例，确认完成后后续消息继续交给 Agent。连接期间不得为同一账号创建第二个接收循环。
5. 前端保留编辑视图以展示等待、成功和错误；允许重试与取消。修改账号参数或禁用时取消过期连接，旧异步结果不得回填新草稿。
6. QQ 出站为 SDK HTTP API、入站为 Gateway WebSocket；飞书出站为应用消息 HTTP API、入站为官方 SDK WebSocket 长连接；Telegram 出站为 Bot API、入站为 getUpdates long polling。单向确认也通过原消息路由发送。

## 内置与用户插件

1. 配送渠道位于 src/workflowweave/plugins/channel/，随 Python 包配送。SystemConfig 新增 builtin_plugin_dir，可显式覆盖内置目录；未设置时发现包内 plugins。plugin_dir 保留为用户导入插件目录。
2. 两个目录由同一个 PluginRegistry 扫描并原子发布，使用相同清单校验、同类 ID 和能力冲突规则；用户插件不得静默覆盖内置插件。两个目录不得指向同一目录。
3. 可写启用设置保留唯一真源 plugin_dir/config.json，适用于两类插件；内置目录不承载运行时可写状态。用户插件自己的 config.json 仍保留原语义。
4. Docker 配送默认插件到独立路径，用户目录单独持久化；不在启动时把默认插件复制或覆盖到用户目录。独立挂载内置目录可以替换配送插件集合。

## 默认值及验证

- 本地状态查询间隔 1 秒，沿用已有扫码连接前端反馈周期。
- 首条消息等待预算 300 秒，与现有扫码接入的人工作业预算一致；不占用单次发送 30 秒预算。适配器启动和确认发送继续使用 ChannelConfig.timeout。
- 临时接收收尾沿用 ChannelManager 的 5 秒停止预算。无有效消息不能成为 connected。
- 定向后端测试每次硬超时 60 秒，随后 lint/类型检查、受影响构建、浏览器 smoke 和授权的真实平台复测。
