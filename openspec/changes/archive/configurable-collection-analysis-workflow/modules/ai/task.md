# AI 全量重写任务（2026-09-19）

状态：重写与 AI 独立验收完成。其他模块正在并行修改，不使用全仓测试作为本轮验收依据。

## 依据与边界

依据 [AI design](./design.md) 四项职责与用户本轮要求：重写 AI 模块，使用 `http://localhost:19026/v1` 的模型 ID `mock` 验证，再使用 `.env` 地址和 qwen3.7-flash 实测。参照 [总 design](../../design.md) 的快照、单次调用、取消与重试边界，以及 [proposal](../../proposal.md) §2.1 的 JSON 模型参数和不采用 temperature/top_k 的限制。proposal/design 本轮不改。

这是结构性重写：旧实现只有模型工厂和单次调用，缺渠道生命周期、模型发现、思考参数验证和错误全文。旧 task 把异常正文全部删除，并把当前 design 没有写明的默认值归因给 design，需要纠正。

## 决策与默认值

- 渠道工厂注入 `ChannelFactory.create(config) -> AIChannel`，渠道拥有 start/create_model/list_models/close。正式仅注册 `http`（OpenAI-compatible Chat Completions），不实现 Responses；`mock` 和 `qwen3.7-flash` 都通过此渠道按模型 ID 调用。
- `AIService` 保留 Workflow 的 execute/validate，增加 start_channel/close_channel/list_models。渠道按 provider/base_url/凭据引用复用；系统提示词与 models 参数不进入连接标识。旧快照变更 URL/凭据后仍可调用旧连接，不缓存对话或结果。显式关闭后必须显式启动，关闭会取消渠道内活动调用。
- `models[model]` 继续作为唯一参数来源。`enable_thinking` 必须为 bool，`reasoning_effort` 只接受 design 的 low/medium/high/xhigh/max；关闭思考与强度同时配置报错。未提供思考选项时不替供应商选择默认值；透传不代表上游一定支持，会如实报告其拒绝。
- 系统提示词独立 SystemMessage；任务提示词仅按字面替换 `{input}`，无占位符则追加输入，保留既有 Workflow 行为，避免把 JSON 花括号解释成模板。
- 非流式 LangChain `ainvoke`，总 timeout=600 秒、retries=5 **沿用当前 AIConfig 与既有调用契约**，不是当前 design 的显式数值要求。预算包含启动、凭据、请求与退避；SDK 重试为 0、阶段 timeout 为 None。重试策略沿用现有 408/429/5xx 和请求被接受前的连接失败；读写断连不自动重试。退避 0.25 秒倍增、最大 8 秒，沿用既有实现并受总预算约束。
- 关闭预算 5 秒沿用现有本地资源清理预算，构造器可配置。取消通过协程取消传播，返回 cancelled 并触发可选同步 `on_cancel(CancellationNotice)`，事件与上下文可用于上层通知；回调失败明确附于取消结果。
- 依 design §4，错误结果保留异常类型、异常全文、traceback 和 HTTP 响应全文，不再用空泛消息掩盖欠费等原因。已解析凭据和 Authorization 值脱敏；不截断错误正文。应用日志保留结构化摘要，完整诊断通过 ErrorInfo.details 交给 Workflow/session（沿用应用日志大小和内容边界）。
- `.env` 最初为两行 URL/model，用户随后补充第三行 key 并授权使用。tests 中的实测辅助代码支持两行/三行格式和显式标准 AI_BASE_URL/AI_MODEL/AI_API_KEY 格式；格式无效立即失败，不猜测可替代模型、不切换地址、不伪造通过。模型测试独立运行，默认请求本地服务的 mock 模型；Qwen 通过显式开关启用。

## 清单

- [x] 重写 channels/manager/prompts/options/errors/service，删除旧 ModelFactory 调用路径。
- [x] 更新 Lifecycle 工厂注入与既有测试注入名称；按用户最新要求，正式验收只运行 AI 独立测试。
- [x] 按用户澄清删除 AI 的本地 HTTP 模拟响应和假模型测试，改用服务提供的 `mock` 模型；当前覆盖与未覆盖项见 tests.md。
- [x] 顺序验证：AI 独立定向测试（硬 timeout 60s）→ lint → build → `.env` qwen3.7-flash 实测。
- [x] 审查 diff，记录真实结果、限制及重现命令。


## 测试与验收

固定测试代码与辅助逻辑集中在 `tests/ai/`；测试范围、断言逻辑、运行命令、预算依据和验收证据统一见 [tests.md](./tests.md)。本 task 只记录实现决策与完成状态。

- [x] AI 独立测试的验证方式和结果统一记录在 tests.md。旧模拟传输测试结果不作为当前测试证据。
- [x] 按用户要求将 AI 测试迁入 `tests/ai/`，同步复用测试工厂的导入路径，默认执行服务端 mock，Qwen 用例通过显式开关启用。
- proposal/design 未改。旧 ModelFactory/models.py 删除；Python 注入接口改为 ChannelFactory/channel_factories。共享 AIConfig 和 Workflow execute/validate 调用契约保持，on_cancel 为可选参数。
