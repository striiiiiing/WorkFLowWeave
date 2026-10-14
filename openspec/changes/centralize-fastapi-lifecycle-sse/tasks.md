# 待完成任务

原方案二实现已撤回，ApplicationLifecycle 仍是当前组合根。本变更的设计继续保留，以下实施与验证项均未完成。

依据：[提案](proposal.md)、[设计](design.md)。

- [ ] 1.1 固定 FastAPI 侧唯一组合根，整理 `interaction/fastapi/` 目录和公共 app factory；删除旧 lifecycle 作为总控制器的调用关系和重复资源入口。
- [ ] 1.2 拆分原 lifecycle：仅将进程级资源所有权、启动顺序、关闭顺序和错误清理接入 lifespan；将请求级访问改为 `Depends`，应用范围实例放入 `app.state`，并保留 workflow run、Agent turn、reload、MCP 调用和 SSE subscription 的操作/会话级生命周期。
- [ ] 1.3 使用 FastAPI 的 dependencies、exception handlers、response models、request disconnect 检测和后台任务改造 interaction 边界，保持现有 HTTP 路径、请求字段、响应业务字段和会话语义。
- [ ] 1.4 将 workflow、channel、agent 事件流替换为 `EventSourceResponse` / `ServerSentEvent`；移除自定义 `StreamingResponse`/SSE 编码和重复 heartbeat。
- [ ] 1.5 验证订阅 finally 清理、客户端断开不取消共享任务、事件 ID、游标、`Last-Event-ID` 和异常传播。
- [ ] 1.6 将 FastAPI 下限提升至 `>=0.135.1`，重新生成 `uv.lock`，并检查环境中 `fastapi.sse` 的导入和运行时行为。
- [ ] 1.7 更新 interaction、lifecycle、SSE 单元测试和最小 HTTP 集成测试；测试比较解析后的 payload，不绑定非 ASCII JSON 的具体字节编码。
- [ ] 1.8 按“定向测试 → Ruff/type 检查 → 受影响包构建 → 最小 HTTP SSE smoke test”的顺序验证，并运行 OpenSpec 严格校验。
- [ ] 1.9 完成 diff 审查，确认没有保留第二套生命周期组合根、重复 SSE 实现或隐式引入 `interaction/api`；记录真实验证结果和未覆盖限制。
