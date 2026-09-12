# v0.2：来源选择、Agent、工具与双向接入

## 1. 任务元信息与范围

依据 [proposal.md](../../proposal.md) §2 延后功能及 §4 前五项，在 v0.1 全部模块测试通过并提交后实施。新增能力保持默认行为兼容：未指定来源时依然使用全部来源，Workflow 通知不创建或切换对话。

## 2. 技术选型（ADR）

待后续讨论。

## 3. 模块与接口

### 3.1 分支来源与 Agent

扩展 AnalysisTask：`source_ids: list[str] | None = None`、`mode: model|agent = model`。子集必须非空、无重复且属于 Workflow.sources；输入按所选列表的顺序从保存的 CollectionResult 重组，恢复仍使用原来源数据。显式空列表不能意外退回全部来源。

AIConfig 增加 `max_steps`、`tool_timeout`、`max_tool_output_bytes`。AIService 的单模型执行接口保持；Agent 入口以相同配置、系统提示词和工具注册表进行有界多轮调用，累计 usage、耗时与工具轨迹。每轮、每工具、整体均受期限约束；非法工具、参数、模型响应和步数耗尽返回明确错误。未显式选用的工具不可被模型调用。

### 3.2 YAML Toolset

`logagent/tools.py` 通过 safe YAML 读取声明：

```yaml
tools:
  - name: recent_runs
    description: Read saved workflow reports
    source: history-source
    parameters:
      type: object
      properties:
        last_n: {type: integer, minimum: 1, maximum: 20}
      additionalProperties: false
    option_bindings:
      last_n: last_n
```

source 引用已保存来源；option_bindings 只覆盖明确允许的 Collector.options，不可替换 collector、资源 ID 或凭据。先验证工具参数 schema，再合并并调用 CollectorManager.validate。返回结构化 CollectionResult，并按工具输出预算明确截断或报错。文件声明不支持任意 shell、Python 表达式或任意动态导入。示例工具与文档纳入交付。

### 3.3 采集源健康

插件可选实现 `async health(options, context) -> HealthResult`，状态 `healthy/unhealthy/unknown`，包含可诊断说明；没有健康接口的插件不能伪装健康。健康配置保存为独立资源，含 source、interval_seconds、timeout、channels、notify_recovery 和 enabled。HealthMonitor 在服务 lifespan 中启动，按配置周期检查；只在状态变化时发送异常或恢复通知，记录最近结果和最后通知状态。每项单独超时，慢检查不阻塞其他检查；通知失败可按下次周期重试。内置 Mock 支持确定地模拟健康变化。

### 3.4 Webhook 与命令

Workflow 增加显式开启的外部触发设置；`POST /api/webhooks/{workflow_id}` 传递触发元数据至同一 WorkflowService，保留请求 ID 和可选事件正文大小上限。可以配置环境变量令牌；未配置时按本地服务模式运行，不另建完整认证系统。

`CommandRegistry` 将完整命令词/别名映射到动作、默认目标和优先级。内置 run/status/cancel/resume/help/use，通过类型化参数调用内部服务，无 shell 执行。匹配以命令词边界为准，最长别名优先，重复别名拒绝。ControlChannel 只有明确启用控制能力后才允许命令。普通通知目标不因此获得控制权。

### 3.5 ConversationChannel 与会话

扩展 BaseChannel 能力接口，ControlChannel 增加 receive，ConversationChannel 增加 reply 和会话路由。实现可通过 HTTP 注入消息的本地双向 Mock，供集成与自托管接入；平台插件可复用同一入口。

`ConversationService` 保存独立 conversation ID、channel ID、用户/会话路由键、明确关联的 Workflow session、AI 配置快照、系统模板和消息历史。系统模板使用 `{workflow_output}` 填入已存最终结果；未保存结果时报告不可用，不重采。API 提供创建、列表、读取和发消息。每个会话使用有界 FIFO，单会话串行、多会话受全局并发限制；空闲队列可回收，正在执行的任务不因队列暂空被清理。关闭先停止接收，再取消/等待消费者。

新 Workflow 通知只发送消息，不更改 conversation 的关联 session；显式 use 操作才切换，并清理或另开上下文防止混淆。重启后能读取消息及上下文关联。API/Channel 与 CLI 共享业务入口。

## 4. 验收与依赖

依赖 v0.1 的所有公共模型、来源、AI、存档、网关、Workflow 和 API。测试覆盖默认全部/子集/非法子集、真实工具调用协议与步数上限、YAML 参数注入边界、健康异常去重与恢复、Webhook 配置/令牌/容量、精确命令匹配、通知与会话隔离、同会话顺序/跨会话并行、重启及关闭。按 tasks.md 模块批次提交后方可进入 v0.3。
