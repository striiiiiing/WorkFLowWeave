# 设计依据与取舍

所有参考均为 2026-09-24 当前工作区源码；旁边项目仅只读研究。路径定位配合类/方法名使用，避免把后续行号变化当成设计变更。

## QwenPaw

主依据：[ChannelManager模块解读.md](../../../../QwenPaw/ChannelManager模块解读.md)。

| 依据 | 本设计采用的内容 |
| --- | --- |
| 解读第 1 节；`src/qwenpaw/app/channels/manager.py` 的 `_make_enqueue_cb`、`_consume_queue` | Manager 管实例/输入队列，具体渠道先 enqueue，再由 Manager 调用通用消费 |
| 解读第 2 节；`src/qwenpaw/app/workspace/service_factories.py` 的 `create_channel_service` | 注入 `process=ws.stream_query` 的方法引用；构造、注入、启动分阶段 |
| 解读第 3 节；`channels/unified_queue_manager.py`、`channels/command_registry.py` | `(channel, session, priority)` 队列和 stop/command/conversation 分类；独立队列不等于协程抢占 |
| 解读第 4 节；`channels/base.py` 的 `_consume_one_request`、`_run_process_loop` | 通道调用注入的 process，消费 Agent 事件后呈现回复 |
| 解读第 5–7 节；Manager 的 `start_all/stop_all/replace_channel/send_text/send_event` | Manager 统一生命周期；主动发送不进输入队列、不调用 Agent |
| `src/qwenpaw/app/channels/qq/channel.py` | 官方 QQ Bot token、Gateway、事件和回复协议 |

相对上述 `src/qwenpaw/app/` 目录查找表内短路径。

明确不照搬的实现：

- `enqueue()` 的 fire-and-forget 和满队列超时后的静默丢弃：这里返回实际入队回执，满载显式拒绝。
- 批量合并失败只消费第一条：这里首版逐条处理，保留每条请求身份。
- 只依据队列为空清理消费者：这里同时检查活动任务，长模型调用不能被空闲清理取消。
- 新通道先启动、旧通道在全局锁内停止：这里先停止旧监听再启新监听，保留在途发送快照，清理不占全局长锁。
- `Workspace` 全对象与 `TaskTracker` 注入：这里只注入 Agent 端口，活动模型任务由已有 AgentService 唯一拥有。

前端差异须如实保留：QwenPaw 的 `src/qwenpaw/app/routers/console.py` 调用 ConsoleChannel.stream_one，而 `channels/console/channel.py` 使用自己的流路径，实际绕过普通 Manager 输入队列。本设计依照用户“前端也得走这个渠道”的要求统一 Web 队列，不声称参考项目已完全如此。

## WorkFLowWeave

| 依据 | 必须保留的约束 |
| --- | --- |
| [原 Channel 设计](../configurable-collection-analysis-workflow/modules/channel/design.md) | send 快照、实例版本、调用总预算、DeliveryResult、无后台发送重试；本变更仅为 conversation 增加入站队列 |
| [Manager 四层设计](../configurable-collection-analysis-workflow/modules/manager%20design.md) | config 唯一合并、插件工厂和 x-workflowweave-workflow 实例/调用选项区分 |
| [Agent 设计](../add-file-centric-agent/design.md) | 双向信封、stop 独立取消、append/compact 安全边界、Agent 与 Workflow 并列、原事件日志唯一事实 |
| [Lifecycle 设计](../configurable-collection-analysis-workflow/modules/lifecycle/design.md) | 全局准入协调、插件活动冲突、失败清理保留引用 |
| `src/workflowweave/agent/service.py` 的 `_admit_message/cancel/wait/events` | 扩展原子等待准入，保留已有模型任务和取消的所有权，不重复建立模型运行时 |
| `src/workflowweave/config/views.py`、`src/workflowweave/channel/manager.py` | 沿用只读注册表及两参数实例工厂、发送执行器和实例缓存 |

上一版 [tasks.md](../add-agent-channels/tasks.md) 是实际代码和历史验证的证据，仅用于确定可保留的协议实现及迁移范围，不能证明新 Manager 架构通过验收。

用户随后明确禁止修改前端。`frontend/src/api/agents.ts` 的 kind/result、TurnAccepted/AgentSession，以及 `frontend/src/composables/useAgentStream.ts` 的原事件信封和 resume(turn_id) 是只读兼容依据；设计通过后端等待入队请求获得真实结果保持这些契约，不把客户端改造作为前置条件。
