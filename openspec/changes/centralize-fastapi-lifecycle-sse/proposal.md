# 在 FastAPI 交互层统一生命周期与 SSE

## Why

当前 `ApplicationLifecycle` 位于独立的 lifecycle 模块，FastAPI 应用只负责调用它；SSE 则由 interaction 自行编码和包装响应。应用入口、资源启动/关闭和 HTTP 流式传输因此分散在两套边界中，维护时需要同时理解 FastAPI 生命周期和自定义传输实现。

本变更采用已确认的方案二：让 FastAPI 成为应用入口、生命周期边界和 SSE 传输边界。这样可以直接使用 FastAPI 提供的原生 SSE 类型，减少重复的响应编码、心跳和断开处理逻辑。

## What Changes

- 让 FastAPI 应用、依赖装配和资源访问成为应用组合根；由 FastAPI 吸收原 `ApplicationLifecycle` 的编排职责，而不是简单搬迁 lifecycle 目录。
- 只把进程级资源的启动、关闭和清理放入 FastAPI lifespan；请求级依赖、状态访问、异常映射和路由行为使用 FastAPI 对应机制承载。
- 使用 FastAPI 原生 `EventSourceResponse` 和 `ServerSentEvent` 承载 workflow、channel、agent 等事件流。
- 保留必要的资源所有权和顺序约束，但不再保留一个包揽所有装配、请求访问和业务交互的独立 lifecycle 外观。
- 保留各业务模块当前的构造注入和直接运行时交互，不在本次引入跨模块 `interaction/api` 依赖层。
- 更新 FastAPI 版本下限、测试和导入路径，验证原有 HTTP 路径、事件字段和会话语义。

## Capabilities

- `fastapi-application-boundary`：FastAPI 统一装配应用依赖并驱动生命周期启动、关闭和失败清理。
- `fastapi-sse-transport`：事件流使用 FastAPI 原生 SSE 响应，保持既有业务事件语义和订阅释放行为。

## Non-goals

- 本变更不实施方案三：Workflow、Agent、Collection、AI、Channel 等模块的跨模块依赖不统一改经 `interaction/api`。
- 不重写领域模块的业务逻辑、持久化模型或业务事件契约。
- 不改变现有 HTTP 路径、请求字段、响应业务字段、会话标识和 Last-Event-ID 语义。
- 不在自定义 SSE 外再保留一套并行的 FastAPI SSE 适配层。

## Impact

- 主要目录：`src/workflowweave/interaction/`、现有 lifecycle 实现及其调用方、`pyproject.toml`。
- 依赖与锁文件：`pyproject.toml`、`uv.lock`。
- 测试：interaction、lifecycle、SSE 传输和最小 HTTP 集成测试。
- 方案三将在后续独立 OpenSpec change 中重新评估和实施，不作为本变更的隐含任务。
