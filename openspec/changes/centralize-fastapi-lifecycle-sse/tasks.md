# 任务与决策依据

依据：[proposal](proposal.md)、[design](design.md)、[FastAPI application boundary 规范](specs/fastapi-application-boundary/spec.md)、[FastAPI SSE transport 规范](specs/fastapi-sse-transport/spec.md)、现有 `src/logagent/lifecycle/` 与 `src/logagent/interaction/` 实现，以及 FastAPI `0.141.1` 中的 `fastapi.sse` 接口。

本 change 只记录方案二的实施任务。方案三“所有模块跨模块依赖都经过 `interaction/api`”不属于本次任务，下一次更新应新建独立 change，不能在本文件中勾选或通过旁路实现提前完成。

## 实施任务

- [ ] 1.1 固定 FastAPI 侧唯一组合根，整理 `interaction/fastapi/` 目录和公共 app factory；删除旧 lifecycle 作为总控制器的调用关系和重复资源入口。
- [ ] 1.2 拆分原 lifecycle：仅将进程级资源所有权、启动顺序、关闭顺序和错误清理接入 lifespan；将请求级访问改为 `Depends`，应用范围实例放入 `app.state`，并保留 workflow run、Agent turn、reload、MCP 调用和 SSE subscription 的操作/会话级生命周期。
- [ ] 1.3 使用 FastAPI 的 dependencies、exception handlers、response models、request disconnect 检测和后台任务改造 interaction 边界，保持现有 HTTP 路径、请求字段、响应业务字段和会话语义。
- [ ] 1.4 将 workflow、channel、agent 事件流替换为 `EventSourceResponse` / `ServerSentEvent`；移除自定义 `StreamingResponse`/SSE 编码和重复 heartbeat。
- [ ] 1.5 验证订阅 finally 清理、客户端断开不取消共享任务、事件 ID、游标、`Last-Event-ID` 和异常传播。
- [ ] 1.6 将 FastAPI 下限提升至 `>=0.135.1`，重新生成 `uv.lock`，并检查环境中 `fastapi.sse` 的导入和运行时行为。
- [ ] 1.7 更新 interaction、lifecycle、SSE 单元测试和最小 HTTP 集成测试；测试比较解析后的 payload，不绑定非 ASCII JSON 的具体字节编码。
- [ ] 1.8 按“定向测试 → Ruff/type 检查 → 受影响包构建 → 最小 HTTP SSE smoke test”的顺序验证，并运行 OpenSpec 严格校验。
- [ ] 1.9 完成 diff 审查，确认没有保留第二套生命周期组合根、重复 SSE 实现或隐式引入 `interaction/api`；记录真实验证结果和未覆盖限制。

## 默认值与决策依据

| 决策/默认 | 理由和依据 |
| --- | --- |
| FastAPI `>=0.135.1` | 当前环境为 `0.141.1`，`fastapi.sse` 已存在；原生 SSE 能力从 0.135 开始，使用 `.1` 作为包含修复版本的项目下限。 |
| 原生 SSE 默认约 15 秒 ping | 采用 FastAPI 原生响应的默认行为，避免维护第二套 heartbeat；只有业务事件需要时才增加明确的进度事件。 |
| lifecycle shutdown/start timeout 不变 | 资源编排被 FastAPI 吸收，但既有进程级资源契约不变；沿用现有实现及其测试依据。 |
| 只有进程级资源进入 lifespan | lifespan 不适合承载请求业务流程、单次订阅和普通 service 调用；这些职责使用 FastAPI dependency、生成器清理和任务协调机制。 |
| `app.state` 保存共享实例 | FastAPI 提供应用范围状态容器；依赖通过它取得唯一实例，避免保留一个巨型 lifecycle 作为第二个服务定位器。 |
| 保留事件字段、ID、游标和 Last-Event-ID 语义 | 用户选择方案二是边界和实现收敛，不是客户端协议重设计；现有前端和调用方继续依赖这些字段。 |
| 领域模块继续构造注入 | 方案三尚未开始；本次只改变 FastAPI/lifecycle/SSE 归属，避免引入第二个依赖抽象和额外迁移面。 |

## 验证记录

本 change 创建阶段只完成 OpenSpec 文档，尚未实施代码，因此上述实施任务保持未勾选。实施完成后必须将真实命令、通过数量、失败原因和剩余风险追加到本节；文档校验通过不能代替业务测试或 HTTP SSE 烟测。
