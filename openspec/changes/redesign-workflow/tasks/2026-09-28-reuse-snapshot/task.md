# 沿用现有 Snapshot 协议

日期：2026-09-28。worktree：`.worktree/redesign-workflow`，分支：`feat/redesign-workflow`。

## 授权、范围与依据

用户明确要求“直接采用原先的snapshot吧，如此也好减少兼容问题”，确认外部传输沿用当前完整 snapshot，并授权将待讨论契约更新为这一决定。本轮修改 [design](../../design.md) 第 4 节、[流式规范](../../specs/workflow-stream-execution/spec.md)和根 tasks，新增本记录；proposal 不变，旧日期任务保留历史。

本轮属于共享前后端协议的设计确认，当前源码已经实现该协议；只读核对现有行为，不把上一轮讨论中的终态常驻连接、最新摘要合并队列或 SSE id 建议写成已批准方案，不修改运行代码。内部原生事件分发和执行/归档验收仍按现行设计单独完成。

## 决策及默认值依据

| 决策 | 当前源码与理由 |
| --- | --- |
| `/api/sessions/{session_id}/events`，命名 `snapshot`，完整 SessionRecord | [routers.py](../../../../../src/workflowweave/interaction/routers.py)、[runEventSource.ts](../../../../../frontend/src/modules/runs/api/runEventSource.ts)；保留已匹配的前后端字段与路径，正文独立按版本读取 |
| 先订阅，再查询首帧；只发送更高版本 | routers.py 的 subscription/initial/stream；队列覆盖查询窗口，版本过滤避免重复和倒退 |
| 客户端按 session 和业务 version 替换 | [useSession.ts](../../../../../frontend/src/modules/runs/composables/useSession.ts)的 accept；execution_epoch 标识轮次，Workflow 不使用 Last-Event-ID 历史重放 |
| 空闲心跳 15 秒 | routers.py 的 `_WORKFLOW_SSE_HEARTBEAT_SECONDS`；[sse.py](../../../../../src/workflowweave/interaction/sse.py)编码注释，不分配业务版本 |
| 单一重连所有者，500ms 起步、5000ms 上限 | [shared/api/eventSource.ts](../../../../../frontend/src/shared/api/eventSource.ts)的 RECONNECT_MIN_MS/MAX_MS；先关闭旧 EventSource，指数退避，连接成功重置，坏帧显式关闭并报错 |
| 对外观察队列容量 64；满队列关闭连接后重连同步 | [progress.py](../../../../../src/workflowweave/workflow/stream/subscriptions/progress.py)的 SUBSCRIBER_CAPACITY；沿用失同步标记和连接释放，容量不是业务数量上限，不适用于内部必要归档 |
| 终态发送一次完整 snapshot 后关闭 | routers.py 的 `_WORKFLOW_TERMINAL` 与 useSession.ts 的终态判断；保留现有终态行为，重跑后刷新重连，其他入口更新由主动同步取得 |
| 离页只释放观察；旧回调隔离 | useSession.ts 的 generation/release/onScopeDispose；关闭订阅、查询和计时器不取消后台执行，仅切换标签页不新增逻辑 |
| EventSource 不可用时明确提示、一次查询和手动同步 | useSession.ts 的 subscribe.available 分支；沿用现有行为，不增加定时轮询 |

## 任务与验证边界

- [x] 核对当前前后端协议、来源常量、终态与离页行为，将用户决定写入 design/specs/root tasks。
- [x] 按新内部执行链路回归真实 HTTP/SSE：首帧竞态、重复旧版本、断线期间终态、快项先可见和正文固定版本读取。
- [x] 回归共用连接、慢观察者满队列、坏帧、终态停止重连、阶段重跑刷新和路由/旧回调隔离；确认观察不会重复执行业务。
- [ ] 真实浏览器验收离页后台继续、返回最新首帧、断网重连与阶段重跑；由 GPT-6 Luna max 使用 Windows Tabbit 执行，不以历史通过记录代替本轮证据。（两次导航到当前 worktree `/workflows` 后约 0.7–1.2 秒复现 `Target page, context or browser has been closed`，未收到 SSE snapshot；Windows curl 对 13000/14300 的 HTTP 健康检查均为 200）
- [x] 执行 OpenSpec 严格校验、限定文件空白及文档差异审查，记录本轮结果。

## 当前 worktree 验收补记

后端 interaction/SSE 与 Workflow progress 定向套件通过；前端 Vitest 49 个文件、244 个测试通过，类型检查、架构检查、Vite 构建和 Playwright E2E 通过。Windows Tabbit 对当前 worktree 的 `/workflows` 导航两次复现 runtime 关闭上下文，未能宣称真实浏览器首帧、终态、重连、离页和阶段重跑已验收。Windows 侧健康检查仍确认 13000/14300 HTTP 200；`live.spec.ts` 中一条过时的“组件健康状态”断言已改为当前页面的“系统状态”。
