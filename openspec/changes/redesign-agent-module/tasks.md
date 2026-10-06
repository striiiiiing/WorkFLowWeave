# Agent 模块重设计实施任务

依据：[proposal.md](proposal.md)、[design.md](design.md)、[规范与测试矩阵](references.md)。详细决策、默认值和交付验证记录在 [task.md](tasks/2026-10-06-agent-module/task.md)。实施已开始；勾选表示已有实现和对应验证证据，不表示整个 change 已验收。最新交接见 [docs 交接文档](../../../docs/redesign-agent-module-handoff.md)。

## 1. 建立实施基线

- [x] 1.1 盘点当前 Python 调用方、内置 registry 路径与 FastAPI change 落地状态，记录已有失败及迁移接线点；以导入清单和基线测试输出验证。
- [x] 1.2 用旧实现生成完成/中断/fork/MCP 与 CLI 交接的合成数据夹具，记录事件 ID 和查询结果；验证夹具可在旧实现独立打开且无真实凭据。
- [x] 1.3 核对 references §4 的疑点，分别标记已有偏差、迁移回归或独立需求；用对应规范和可复现测试记录结论，不修改既有设计迁就实现。

## 2. 建立共享存储原语与值对象边界

- [x] 2.1 设计并实现 `src/logagent/storage_primitives/` 的 atomic、locks、digest、revision、jsonl、sqlite、paths 原语；用临时目录/SQLite 的并发、崩溃和 revision 测试验证，且静态检查不得导入 agent/workflow。
- [x] 2.2 提取 contracts、实际依赖 ports 和 ToolDeclaration，保留 config 唯一默认值；用导入检查和原配置/工具声明测试验证。
- [x] 2.3 迁移 workspace/files、views 和进程/沙箱模块，保持路径、ETag、self.json 和取消语义；通过矩阵 A5/A7/A11 验证。
- [x] 2.4 迁移 Agent events/artifacts/settings/bindings，使其委托 storage_primitives，提取 Sessions 投影和官方 LangGraph checkpointer 适配；通过稳定键复用、原始输出、绑定损坏和原数据布局测试验证。

## 3. LangGraph 主运行时

- [x] 3.1 定义 AgentState、AgentContext 和 graph topology，使用 StateGraph/context_schema/Runtime（含 context、stream_writer 和受控 store 入口）；验证 model→tools→model、终态和旧 checkpoint thread_id 兼容，且 store 不成为第二事实源。
- [x] 3.2 将统一工具执行流程接入 LangGraph ToolNode，从 ToolRuntime/真实 tool_call_id 到 tools/executor；用 A4/A7/A8 的并发、异常、取消和结果先提交用例验证没有旁路。
- [x] 3.3 接入 RunnableConfig、checkpointer、astream/astream_events 和 stream_mode，保证一次 turn 只启动一条图流；用真实框架契约及 test_task_ownership 验证，不只用 mock 图。
- [x] 3.4 使用 Command 更新/跳转处理 append、compact、stop 边界，只有确认型动作才使用 interrupt；用命令排队、取消、恢复场景验证不产生伪造 turn。
- [x] 3.5 提取 context 的 prompt/budget/compaction middleware 和 recovery 与 session fork 协调；用 A5/A6 及旧夹具验证消息配对、失败保留、缺 checkpoint 明确失败、未知工具不重放、父分支不变。

## 4. 切换所有权与应用接线

- [x] 4.1 将 session 值与 ActiveTurn 分离，由 turns 独占准入/任务表/待处理命令；用 A1/A2 验证双来源竞争、重复提交、stop/append/compact 和关闭竞态。
- [x] 4.2 提取 integrations 的资源捕获、AI 租约、MCP 与 Workflow 适配，Service 移除具体依赖构造；用 A8/A9 及 turn_config 验证冻结范围与原始结果。
- [x] 4.3 迁移渠道侧 processor 并将 AgentChannel 改为 CommandDispatcher，更新所有调用方；用 A2/A3 验证同一队列、改绑与原路回复，删除旧转导。
- [x] 4.4 与 FastAPI change 的唯一组合根接线，启动失败也能清理已创建资源；用 A10 验证 lifespan、原 HTTP 路径和 SSE 断开/重连，不新增第二套 heartbeat。
- [x] 4.5 更新 registry 内置模块定位并删去 Service 的默认工具副本及旧路径；用工具关闭不导入测试、静态依赖检查和全仓旧导入扫描验证。
- [x] 4.6 在 `frontend/src/modules/agents/langchain/` 实现 `@langchain/vue` 的 `useStream` 与 LogAgent `AgentServerAdapter`，迁移 Agent 页面流状态和测试；用真实 v2 adapter 契约、重连、fork、stop 和组件卸载验证不再存在第二套 EventSource 状态机。

## 5. 回归与完成

- [ ] 5.1 按目标目录迁移既有测试，执行 A1–A11 及 storage_primitives、LangGraph runtime、LangChain Vue adapter 的跨边界场景；每次后端单测命令设置 60 秒硬超时，记录结果，失败不得静默跳过。
- [ ] 5.2 运行静态依赖/lint、受影响 Python 包构建、前端 typecheck/build 和最小真实应用 smoke；验证会话发送、工具结果、停止、SSE 重连、前端卸载与重启后查询。
- [ ] 5.3 核对 design §7 所有旧职责已迁移、无重复任务/存储/默认工具来源/前端 stream 状态；用 diff review 和导入扫描验证，保留用户已有改动。
- [ ] 5.4 运行 OpenSpec 严格校验，核对所有实现任务的测试证据；仅全部验收后归档本 change，保持 skip_specs，不替其他活动 change 同步业务规范。
