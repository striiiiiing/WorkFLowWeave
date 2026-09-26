# 按 ChannelManager 重新设计双向渠道

用户要求以旁边 QwenPaw 的 `ChannelManager模块解读.md` 和对应源码为依据重新设计。上一版把 Web 接到 Agent 命令门面，把 QQ/test 接到另一个运行时；共享命令解析没有实现统一的渠道管理、队列和消费流程。

本变更替代 [add-agent-channels 的架构方案](../add-agent-channels/design.md)，保留其需求：QQ、双向测试渠道、前端统一渠道、双向仅绑定 Agent，以及可独立供 Workflow 等模块调用的单向 `send`。新增本变更是为了保留上一版设计、任务和验证记录，不能把旧版完成记录当作新版验收。

本轮交付重设计、channel 能力增量与实施任务；代码迁移尚未实施。技术方案见 [design.md](design.md)，依据见 [references.md](references.md)。

用户追加约束：不允许修改前端。统一 Web 渠道由后端兼容现有请求、响应与 SSE 完成，不新增前端状态、协议字段或前端实施任务。
