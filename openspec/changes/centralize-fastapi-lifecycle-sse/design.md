# 设计

## 1. 应用边界与 lifecycle 吸收

`interaction/fastapi/` 是外部 HTTP 和应用组合根。FastAPI 不再只是调用一个外部 `ApplicationLifecycle`，而是直接承载资源装配、依赖暴露、异常映射和路由注册。领域模块仍由构造参数获得依赖；FastAPI 侧负责应用编排，不把业务规则搬入路由。

目标结构可以保留生命周期相关的内部辅助模块，但不得以目录移动冒充架构吸收。具体文件名可在实施时按现有模块拆分调整：

```text
src/logagent/
  interaction/
    fastapi/
      app.py
      dependencies.py
      errors.py
      schemas.py
      sse.py
      routers/
        workflow.py
        agent.py
        channel.py
        resources.py
        system.py
  agent/
  ai/
  channel/
  collection/
  config/
  mcp/
  workflow/
```

原 `ApplicationLifecycle` 不再作为 FastAPI 外部的总控制器被调用。其真正必要的资源初始化、释放和顺序约束应拆分到 FastAPI app factory、lifespan context manager、依赖提供函数和资源适配器中；只有在拆分后仍有清晰职责的纯资源协调函数可以保留。迁移期间不得保留一个“新 FastAPI 调用旧 lifecycle”或“旧入口继续独立启动”的双重组合根。

## 2. FastAPI 机制分工

- **lifespan**：只处理进程级、跨请求资源，例如数据库连接池、共享 manager、后台监听器和应用关闭清理。这里不放请求业务流程、单次订阅、路由参数校验或普通 service 方法调用。
- **依赖注入**：用 `Depends` 提供请求级服务、会话、鉴权上下文和资源句柄；依赖从 `app.state` 读取已装配资源，避免路由自行创建全局对象。
- **`app.state`**：保存 FastAPI 应用范围内的唯一服务实例和关闭协调状态，不再通过一个巨型 lifecycle 对象作为所有访问入口。
- **异常处理**：用 FastAPI/Starlette exception handler 将领域异常映射为现有 HTTP 错误格式；不在 lifecycle 中捕获并吞掉请求异常。
- **路由与响应**：使用 FastAPI 的路由声明、响应模型、依赖缓存、后台任务和请求断开检测；业务层只返回领域结果，不重复包装 HTTP 对象。
- **CLI/测试**：复用 app factory 和依赖覆盖，不复制另一份资源图；需要离线测试时使用 `app.dependency_overrides` 注入替身。

### 2.1 当前代码中的资源分层

不能把所有非 lifespan 对象都称为“请求级依赖”。当前实现至少有三种生命周期：

| 层级 | 当前对象/状态 | FastAPI 承载方式 | 不能做什么 |
| --- | --- | --- | --- |
| 进程级资源 | `JsonLogSink`、`SessionStore`、checkpointer context、`PluginRegistry`、`CredentialManager`、`MCPRuntime`、`CollectorManager`、`AIService`、`ChannelManager`、`ResourceStore`、`WorkflowRunner`、`SessionView`、`AgentService`、`WorkflowScheduler`、`MCPHealthMonitor`、`ApplicationServices` | app factory 创建；共享引用放入 `app.state`；进程级 start/stop 由 lifespan 管理 | 不在请求中重复创建；不因单个客户端断开而关闭 |
| 请求级依赖 | `Request`、请求参数模型、鉴权/会话上下文、从 `app.state` 取出的单次访问句柄、请求结束即失效的临时校验结果 | `Depends`、Pydantic 参数模型、`Request`/`BackgroundTasks` | 不持有共享 manager 的所有权；不负责全局 shutdown |
| 操作/会话级 | workflow run、Agent turn、channel 入站请求、reload 操作、MCP 单次调用、SSE subscription、progress hub subscriber | 由领域服务或生成器创建；路由只负责提交、等待、订阅和断开协调；必要时使用 `BackgroundTasks` 或任务协调器 | 不随 lifespan 结束前的普通请求返回而强行销毁；SSE 断开只释放 subscriber，不取消共享 run |

现有 `ApplicationServices` 是进程级引用容器，不是请求级依赖本身。`get_services()` 应保持为轻量的 FastAPI dependency：它只从 `request.app.state` 读取容器并检查 ready 状态。

### 2.2 进程生命周期

- FastAPI lifespan 是进程级资源启动/关闭的唯一入口。
- lifespan 按现有顺序创建资源；任一资源失败时，释放已成功创建的资源并报告原始异常。
- 应用关闭时沿用现有 shutdown 顺序、超时和取消语义；只有这些进程级语义进入 lifespan。
- 请求级订阅、单轮 workflow/Agent 执行和普通 service 调用由路由依赖、生成器 `finally` 或任务协调器管理，不挂到 lifespan 的退出逻辑。

## 3. 原生 SSE

workflow、channel、agent 的事件路由改用 FastAPI 原生 SSE：生成器产生 `ServerSentEvent`，路由声明 `EventSourceResponse`，由 FastAPI 处理 `text/event-stream` 响应格式、缓存控制、断开检测和默认 ping。

```python
@router.get("/events", response_class=EventSourceResponse)
async def events(...):
    yield ServerSentEvent(
        data=payload,
        event="snapshot",
        id=event_id,
    )
```

实施时删除 `StreamingResponse` 自定义包装、重复的 `encode_sse` 和第二套手写 heartbeat。业务生成器仍必须在 `finally` 中释放订阅、取消监听任务和关闭临时资源；客户端断开不得把共享 Agent 或 workflow 任务误取消。

事件名、事件 ID、数据字段、会话过滤、游标和 `Last-Event-ID` 的业务语义保持现有契约。原生 SSE 的 JSON 序列化可能改变非 ASCII 字节表示，因此测试比较解析后的字段和事件语义，不固定中文的具体字节转义形式。

FastAPI 原生 SSE 的约定作为默认值来源：`text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no` 以及约 15 秒的空闲 ping。不得再新增一套不同间隔的应用 heartbeat；若某个业务流需要更短的进度信号，必须有明确的业务事件依据。

Agent 流实现应优先等待事件或通知，不能因为迁移而继续增加无意义的固定 0.5 秒轮询。现有轮询只有在事件源无法等待且测试证明需要时才保留，并在任务中记录原因。

## 4. 依赖与范围

本次只收敛 FastAPI 应用入口、应用资源编排和 SSE 传输边界。Workflow、Agent、Collection、AI、Channel 之间现有的构造注入和直接服务调用保持不变；不新增 `interaction/api` Protocol 作为跨模块门面，也不把所有依赖包装成 HTTP 调用。

方案三需要单独设计调用方向、协议模型、错误语义和测试边界，作为后续 change 处理。本变更中的目录迁移不得预留旁路 API 以假装完成方案三。

## 5. 版本与兼容

项目 FastAPI 版本下限提升至至少 `>=0.135.1`，以保证 `fastapi.sse` 的原生 SSE 类型可用；上限仍沿用当前 `<1` 约束。锁文件应在实施时重新生成。

业务 SSE 的事件字段和 API 路径不变。测试需覆盖正常订阅、断开清理、空闲 ping、Last-Event-ID 恢复、生成器异常和 lifecycle 启动失败；不以旧的自定义编码函数继续存在作为兼容目标。
