# AI 任务：以 LangChain Model 为调用核心

状态：实现、主代理审查和验证完成。旧任务的完成标记不作为本轮验收证据。

## 依据与提交差异

事实依据为当前 [AI design](./design.md)、[总 design](../../design.md) 与 [proposal](../../proposal.md)。本轮不修改 proposal/design；重写本 task，因为实现计划尚未反映当前设计。contracts 只同步派生说明。

| 对照基线 | 已有行为 | 本轮处理 |
| --- | --- | --- |
| `5b90965` | 模型字段和兼容默认值存在多个来源 | 不恢复旧兼容层；继续使用唯一的 `AIConfig.models` 和显式 model |
| `9bbda93` | 自定义 Provider.complete、手写 HTTP 请求、内置回显 Mock；5xx 不重试 | 删除旧 Provider 调用抽象及生产 Mock；用 LangChain BaseChatModel.ainvoke；调整状态重试 |
| `3f4ab74` | design 新增 LangChain Model；task 要求 408/429/5xx 重试并及时汇报，但代码尚未落实 | 以新 design 为准重写计划，验证实际 SDK 请求次数及错误日志 |
| 当前未提交修改 | design 明确异步、渠道管理、无状态；已有 ChatOpenAI 包装及依赖，但仍套用旧 Provider 协议，测试未更新 | 复用正确依赖与异步方向，将渠道配置转换为 Model，删除重复调用路径 |

## 实现决策

这是结构性修改：调用、错误转换、重试和测试注入跨越同一边界，不能只替换 HTTP 方法。`AIService` 负责验证配置、选模型、提示词和总预算；注入的模型工厂负责从渠道配置创建 LangChain `BaseChatModel`；正式工厂仅实现 OpenAI-compatible（保留配置标识 `http`，避免无意义重命名已存资源）。OpenAI Responses/Anthropic 暂不实现，未知接口显式拒绝。

- 同一 AIConfig 共享 base_url、凭据和 system_prompt，多个 models 各自携带 JSON 参数；每次执行从配置副本创建模型，不维护对话历史、持久化或业务结果缓存。Workflow 仍负责分支和汇总。
- `ChatOpenAI` 固定非流式 Chat Completions；`AIService` 直接 await `BaseChatModel.ainvoke`。AIService 构造器显式接收 model_factories，Lifecycle 装配默认 http 工厂，业务服务只依赖工厂协议。模型工厂可注入测试模型，但生产不再注册回显 Mock，也不保留 Provider.complete 兼容层。
- timeout=600 秒、retries=5 来自 AI design 对非流式长思考的说明；总预算覆盖凭据解析、模型调用与退避，至多 1+retries 次。SDK max_retries=0，禁用短阶段 timeout，避免双层预算与重试。退避沿用 `9bbda93` 的 0.25 秒指数增长、最高 8 秒，受总预算约束。
- HTTP 408/429/5xx 重试来自 `3f4ab74` 的用户任务修正；连接前失败继续可重试。认证/参数/响应结构错误立即失败；读取断连仍标记 uncertain，不引入未要求的盲目重试。每次失败在等待前记录事件、尝试次数、状态码和是否重试，最终失败返回 AnalysisResult，日志不含凭据、输入或上游响应正文。
- JSON 模型参数传入 ChatOpenAI 的 extra_body，以保留供应商扩展字段；请求 model/messages、连接、流式和重试字段归服务所有，不得被模型参数覆盖。temperature/top_k 仍依据 proposal §2.1/§2.2 排除，不把旧 task 作为独立限制来源。
- 独立 SystemMessage/HumanMessage；{input} 按字面替换，无占位符时沿用追加完整输入。返回必须是可消费的非空文本 AIMessage；拒绝、工具调用或非法返回不能伪装成功。
- close 释放自有 HTTP 连接，外部客户端仍由注入者负责；清理默认 5 秒沿用已有本地资源释放预算，可显式配置。取消不得产生后续请求。
- 依赖下限采用本轮实际验证的 langchain-openai 1.6.2，使用其异步凭据 supplier、连接设置和异常转换；无凭据时显式使用 SDK Omit，防止隐式读取环境 API key，也支持无认证的本地兼容服务。LangChain 会再包装 SDK 连接异常，因此沿 APIConnectionError 原因链识别 HTTP transport 失败，不能只看一层 cause。

## 执行清单

- [x] 将模型工厂与单次执行职责分离，移除 Provider/HTTPProvider/MockProvider，改用 BaseChatModel/ChatOpenAI。
- [x] 更新必要装配与测试注入，保持 Workflow execute/validate 接口及单一配置来源。
- [x] 验证真实 ChatOpenAI 异步请求、角色/参数/模型隔离、认证、超时、重试、日志、取消、无效响应和客户端关闭。
- [x] 同步派生契约和总任务状态；审查全部 diff，针对性测试（硬超时 60 秒）→ lint → build → 离线 HTTP 烟测。

## 本轮验证

- AI/Workflow 集成/Lifecycle/日志定向：77 passed，18.43 秒，exit 0。
- AI 专项最终补充：55 passed，12.17 秒，exit 0，覆盖真实 ChatOpenAI 异步请求与本轮新增边界。
- 最终代码全套：`timeout 60s uv run --frozen pytest -q --tb=short`，590 passed，51.59 秒，exit 0。仅有 LangGraph allowed_objects 与 Starlette/AnyIO 的上游弃用提示；全套包含工作区已有 Lifecycle/Interaction，不代表这些模块另行验收。
- AI、受影响装配/日志与测试的 Ruff 检查通过；`uv build` 成功生成 wheel 与 sdist。
- 本地真实 TCP HTTP 烟测通过：ChatOpenAI.ainvoke 请求 `/v1/chat/completions`，服务先返回 503 后成功；验证两次请求完全一致、system/user 角色、参数、usage 和自有客户端关闭。未访问外部付费模型服务。
- 主代理独立审查任务与实现；子代理因用户报告欠费停止，剩余工作由主代理完成。清理了旧 Provider/HTTPProvider/MockProvider 的生产实现和所有调用引用，未保留双重模型调用协议。

## 变更位置与兼容边界

- `src/logagent/ai/models.py` 定义 ModelFactory 协议和 OpenAIModelFactory；`service.py` 负责异步执行、错误转换、总预算及日志。
- Lifecycle 将原 providers 注入改为 model_factories，装配默认 http 工厂；日志 formatter 保留 attempt/will_retry/status_code/uncertain。离线模型放在 `tests/ai_helpers.py`，Workflow 与 Lifecycle 测试显式注入。
- `AIService.execute/validate`、AIConfig 和 Workflow 快照结构不变；旧 Python providers/complete 注入接口删除，调用方需改用工厂 create → BaseChatModel。生产配置不再支持回显 mock；OpenAI-compatible 仍使用 provider=http。proposal/design 保持用户当前版本。
