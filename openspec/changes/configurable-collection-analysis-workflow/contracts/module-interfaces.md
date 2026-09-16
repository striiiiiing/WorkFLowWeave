# 模块接口契约（设计派生说明）

以[总设计](../design.md)和各模块 design.md 为依据；并纳入用户本次确认的 session 存储调整；本文件不构成独立事实来源。配置资源保存为版本化 JSON；独立 SessionStore 保存可读业务数据，LangGraph SQLite checkpointer 保存执行进度和恢复状态。

## 配置与插件

`PluginRegistry.discover_plugins(config)` 扫描 manifest、导入 entry.backend 并调用同步 plugin.register(api)，发布只读 collectorRegister/channelRegister。reload_plugins 按 owner 替换声明，不影响其他 owner。

公共 `ResourceReader` 协议提供 get/list/resolve/snapshot；`ResourceStore` 在其上增加 save/delete/reload_resources。resolve 返回模板与本地 Setter 合并后的有效 SourceConfig；snapshot 固定同一有效资源视图。调用者依赖协议，不依赖 JSON 仓库实现。业务校验由配置模块注入，文件保存使用临时文件与原子替换。

`CollectorRegistryView` 和 `ChannelRegistryView` 提供 get/describe/diagnostics，只发布能力，业务模块不自行扫描插件目录。options defaults 的解释属于配置模块，不由调用阶段重新合并。

## Collection 与历史读取

CollectorManager 提供 describe、无 I/O 的 validate，以及异步 collect(source, context)。Collector 通过插件声明名称、schema、字段和 collect 协程，返回统一结果。

历史 Collector 从 CollectionContext.session_reader 获得 `SessionReader`。它不重新运行历史 Workflow 或原始来源，也不读取 SQLite 表或具体 WorkflowService：

```python
class SessionReader(Protocol):
    async def list_sessions(
        self, workflow_id=None, *, limit=100, offset=0,
        after=None, before=None, exclude_session_id=None,
    ) -> list[SessionRecord]: ...
    async def get_session(self, session_id, *, version=None) -> SessionRecord: ...
    async def get_phase_content(self, session_id, stage, *, version) -> PhaseContent: ...
```

SessionView 只读取 SessionStore，列表返回每个 session 的最新业务版本，每个 session 只出现一次，按创建时间降序、同时间按 session_id 排序；after/before 是创建时间的包含边界。limit 默认 100 沿用现有查询分页大小，实现须校验 limit>0、offset>=0 和时间区间。历史 Collector 排除当前 session，按次数、时间和内容预算选择后固定正整数 version；正文读取必须保持该版本。无匹配为 empty，已选正文不可用须报告具体原因。API 与历史 Collector 使用同一 SessionView 实现。每次新的逻辑写入递增 version，重放不递增；公共协议仅允许读取，写入协议保留在 Workflow 内部。

## AI 与 Channel

AI 接收明确的配置、prompt 和 input，返回 AnalysisResult；多模型配置与请求默认值由 AI 模块统一维护。

ChannelManager 依据 channel ID 与有效配置版本复用长期实例；首次发送前只初始化一次，在卸载或系统关闭时 stop。并发发送、配置替换及旧快照使用保持相应实例生命周期。每次 send 只处理一条 Notification 并返回 DeliveryResult，不排队、不缓存消息、不自动重试。Mock 专用持久 logging Handler 追加 UTF-8 标题和正文文本；不得混入应用诊断日志或将其改成 JSON 记录。

## Workflow

WorkflowService 提供 validate/save/trigger/recover/cancel/shutdown；RunCoordinator 管理全局容量、session 互斥、活动任务与 LangGraph 生命周期。固定 collect → analyze → aggregate → notify → finish 流程，采集与分析使用子图。父图及子图以 session_id/thread_id 关联执行进度；checkpointer 负责恢复。业务节点通过 Workflow 内部写入协议幂等维护独立 SessionStore 的状态、内容和回执，SessionView 从 SessionStore 读取，不能解析 checkpoint 替代业务查询。可复用的参数化闭包节点可供父图和子图调用，避免重复写入实现；幂等逻辑写入不会增加 version。

恢复同时检查原 checkpoint、原快照和所需阶段正文，从原 thread_id 继续；缺少 checkpoint 时不得根据 SessionStore 的阶段标签猜测执行位置。成功分析及投递不重做，发送意图存在但缺少确定回执时标记 delivery_uncertain，不自动补发。输出冻结后恢复只发送原输出。备份策略覆盖 SessionStore 正文以及 checkpointer 确需保留的正文副本（父图、子图、历史 checkpoint 和待提交写入），正文缺失/过期不冒充空结果。状态、错误及可用性始终保存在 SessionStore；checkpointer 不代替可读数据仓库。

## 交互与生命周期

API/CLI 调用应用服务，映射统一 ErrorResponse；取消以 session_id 定位活动运行，不依附原 HTTP 请求。生命周期装配资源仓库、插件注册、SessionStore、checkpointer 和共用 SessionView，在接收运行前将遗留 created/running session 标记 interrupted，关闭时停止接收、释放活动任务和长期渠道实例。
