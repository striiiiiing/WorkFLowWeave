# Agent 设计与实施任务

本文件是 OpenSpec CLI 入口。新版设计依据、默认值和实现边界记录在 [设计修订任务](tasks/2026-09-22-design-revision/task.md)；现行实现和验证证据见 [实施与审核记录](tasks/2026-09-22-implementation/task.md) 的本轮完成点、F6 最终验收及 C6 公共 Collector 入口补漏。实施记录中的旧过程保留为历史，本索引依据2026-09-23最终代码与验证更新。

本轮 F1–F4、F5a、F6 已完成。依用户最新授权，真实浏览器操作、窄屏视觉和浏览器 SSE 由用户独立方案验收，F5b 保持未完成，不属于本轮阻塞。本轮没有启动浏览器或准备浏览器依赖。

## 1. 文档与授权

- [x] 1.1 用户已要求基于新版 `design.md` 重新整理各部分，并授权本轮直接修改设计及派生文档。
- [x] 1.2 修改前创建基线提交 `65d600e`；后续文档修改不代表产品代码已完成。
- [x] 1.3 重写 `design.md` 内的冲突段落，保持原章节结构并记录 checkpoint、并发、工具数量和缓存边界。
- [x] 1.4 同步 proposal、frontend、references、runtime/interface specs。
- [x] 1.5 校准 Runtime 可读文件路径，并将 checkpoint 清理统一为整条 thread 生命周期规则；依据见 [设计一致性校准记录](tasks/2026-09-22-design-alignment/task.md)。
- [x] 1.6 修正多会话 Runtime 入口：使用会话作用域的 `Runtime/self.json`，不使用共享工作区的 `Runtime/current.json`；依据见 [会话上下文入口记录](tasks/2026-09-22-session-context/task.md)。

## 2. 实施顺序（新版）

- [x] 2.1 验证锁文件中的 LangChain/LangGraph 1.x、checkpoint/sqlite、Provider 与 Workflow 副本回归；不在 SQLite 中直接删除中间 checkpoint。
- [x] 2.2 抽取共享模型租约和无工具 Workflow 文本入口；验证 Agent tool calling/streaming 入口。
- [x] 2.3 扩展 PluginRegistry 的 tool kind、Collector 调用 Schema 投影、公共 HTTP/CLI/application service 和五个内置工具插件。公共 Collector HTTP/CLI 已按 C6 补齐：Agent/HTTP 共用调用服务、CLI 包装 HTTP，新增32项自动化测试及关闭 Shell、持工作区写锁时的真实 HTTP/CLI 烟测通过。
- [x] 2.4 实现固定工作区级读写调度、取消、稳定 tool key、事件 JSONL 和 `created_at/updated_at` thread 元数据。
- [x] 2.5 实现文件记忆、Runtime 映射、bubblewrap/关闭模式、按日时区和 Artifact 预算。
- [x] 2.6 实现 Workflow 结果续接、命令优先级、`/append`/`/compact` 边界、Pi 式 fork 分支和模型输出只读。
- [x] 2.7 实现设计规定的默认200,000上下文预算、180,000触发/40,000保留的绝对 token 阈值、可编辑 summary prompt、一次压缩失败边界和 ToolMessage 配对。
- [x] 2.8 实现 HTTP/SSE/Vue 页面、断线续传、文件 If-Match、工具/沙箱设置和 Workflow 最新结果入口。
- [x] 2.9 验证重启中断、未知副作用不重放、整条 thread 生命周期清理、旧 Workflow 回归和真实本地 SSE 烟测。

## 3. 通用验证门槛

- [x] 3.1 变更行为的后端单测硬超时 60 秒。
- [x] 3.2 Python 静态检查、前端类型检查和受影响包构建；前端以只含本任务精确改动的隔离检出为证。
- [x] 3.3 使用临时工作区/mock Collector 做最小集成验证，不发送真实渠道。
- [x] 3.4 对照 [design.md](design.md) 审查：无第二份 Schema/配置/连接池、无隐藏工具、无 catch-all 成功、无自动重发、无链上中间 checkpoint 删除。

验证范围：Agent/HTTP最终124项、最后预算字段定向28项、旧Workflow 67+3项及确定性lifecycle/AI租约43项通过；新增Agent前端16项均通过，隔离类型/构建、Python静态/构建、非浏览器真实HTTP/SSE和OpenSpec严格验证通过。共享工作树的另一个Demo文件存在TS6133，本地AI mock服务返回内容与既有两项测试期望不符；完整失败与隔离边界见实施记录，不声称整个共享工作树或后端全量测试全绿。
