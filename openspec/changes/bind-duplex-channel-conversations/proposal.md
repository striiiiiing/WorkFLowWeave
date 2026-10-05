# 双向渠道实例拥有 Agent 对话

状态：2026-10-05，依据用户本轮明确要求记录设计，尚未实施。

## Why

现有渠道设计以平台好友、群成员等对端身份自动创建和选择 Agent 对话，缺少渠道实例上的显式绑定入口。此前讨论的“Agent 对话选择渠道”方向错误；`enqueue(wait_result=...)` 也将入队和等待 Agent 操作结果组合成两种调用模式，增加了接口含义。

用户确认的归属是：一个双向渠道实例绑定一个 Agent 对话。同一种渠道能力可以创建多个实例；Agent 对话不保存渠道选择，发送时由渠道侧确认绑定。

## What Changes

- 渠道侧保存实例到 Agent 对话的绑定；初始无绑定，前端在双向渠道实例处选择或解除绑定。
- 同一实例的入站消息只交给它绑定的对话；好友、群、发送者等是来源与回复路由信息，不再自动决定另一个 Agent 对话。
- 入站提交后由现有统一队列消费，高优先级指令进入指令处理通道；移除 `wait_result` 模式，区分入队、Agent 操作结果和发送确认。
- Agent 输出由渠道侧确认实例当前拥有的对话及可信发送目标，再调用平台发送 API；对话本身不保存渠道字段。
- 被渠道绑定的对话仍可从 Web 查看、订阅事件并进行调试，使用同一 Agent 对话和事件日志。
- Email/file 等单向渠道仅服务现有 Workflow 通知路径。Workflow 向双向渠道发送通知时复用同一适配器和平台发送 API。

## Capabilities

- `channel`：实例级对话归属、指令分流、出站绑定确认和 Workflow 通知复用。
- `frontend`：双向渠道实例的绑定管理与 Web 对话查看。

## Impact

预计涉及 ChannelManager、Agent 渠道处理端口、ChannelBindings、渠道管理 API、前端渠道实例页面及契约测试。AgentSession 不增加渠道字段；六个插件的位置、Email SMTP 和 file logging 方案保持依据原通知插件设计实施。

本变更替代 `redesign-agent-channel-manager` 中按平台对端自动建对话的规则，并替代近期实现中的 `wait_result` 模式；本轮只提交 OpenSpec 文档，不修改实现。

## Future Work

后续将单向渠道 `send` 封装为 CLI，供 Agent 调用；未来 Skill 系统提供相应使用能力。这里只记录方向，CLI、Agent 工具与 Skill 的实现均不纳入本变更。
