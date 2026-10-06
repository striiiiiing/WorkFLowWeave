# Interaction 原生 SSE 实施记录

依据：[proposal](../../proposal.md)、[design §3](../../design.md)、[FastAPI SSE transport 规范](../../specs/fastapi-sse-transport/spec.md)，以及当前 `src/workflowweave/interaction/` 的三条事件路由。

## 范围与决策

- 本次只实施 interaction 的 SSE 传输边界，不勾选或声称完成该 change 中尚未实施的 FastAPI lifecycle/application boundary 任务。
- workflow、channel、agent 路由改为异步生成器并声明 `response_class=EventSourceResponse`；事件由 `ServerSentEvent` 表达，保持原路径、事件名、事件 ID、游标和 `Last-Event-ID` 语义。
- agent 和 workflow 的订阅/首帧校验放入 FastAPI dependency。这样缺失会话仍在响应开始前映射为现有领域错误，同时依赖的 `finally` 在流结束或断开时释放订阅。
- 删除 interaction 自定义 `StreamingResponse`、JSON 编码和 heartbeat。FastAPI 原生约 15 秒 ping 作为空闲保活默认值；Agent 事件等待从原先的 0.5 秒轮询调整为 15 秒条件等待，避免重复发送无业务意义的 heartbeat。
- `fastapi` 下限从 `>=0.115` 提升为 `>=0.135.1`，理由是 design §5 要求使用 `fastapi.sse` 原生类型；锁文件同步项目依赖约束。

## 实施文件

- `src/workflowweave/interaction/channel_routers.py`：共享 Agent SSE 依赖和原生事件生成器。
- `src/workflowweave/interaction/agent_routers.py`：Agent 路由声明原生 SSE 响应。
- `src/workflowweave/interaction/routers.py`：Workflow snapshot SSE 改为原生响应和依赖清理。
- `src/workflowweave/interaction/sse.py`：仅保留 FastAPI `ServerSentEvent` 类型别名，不再实现第二套编码器。
- `tests/interaction/test_sse.py`：验证原生响应头、事件字段、Unicode JSON payload 和元数据校验。

## 验证

- `uv run --no-sync pytest -q tests/interaction`：61 passed。
- `uv run --no-sync ruff check src tests`：通过。
- `uv lock --offline`：通过并更新 `uv.lock` 中的 FastAPI 约束。
- `git diff --check`：通过。

现有 HTTP/SSE 集成测试覆盖首帧、游标恢复、终态尾部事件、客户端断开不取消 Agent turn，以及 Workflow 订阅清理；本次未扩展浏览器端到端范围。
