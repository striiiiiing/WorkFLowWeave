# AI 模块设计（v0.1）

依据：[模块 proposal](./proposal.md)、[根 proposal](../../proposal.md) §2.1、§3，以及[根设计](../../design.md) §4.1–§4.2、§5。本文件细化首版可复用分析能力，公共模型仍定义在 `logagent/models.py`。

## 1. 职责与结构

AI 模块接受确定的模型配置、任务提示词和输入文本，完成一次有界分析，返回 `AnalysisResult`。Workflow 决定何时执行、分支并发、失败策略、备份和结果用途；AI 不读取最新 Workflow 配置，不采集数据，不发送通知。

| 子模块 | 建议文件 | 职责 |
| --- | --- | --- |
| 服务入口 | `logagent/ai/service.py` | 配置校验、消息装配、总超时、执行结果标准化。 |
| 提供方适配 | `logagent/ai/providers.py` | 离线 Mock 与 HTTP 兼容聊天模型；管理协议差异。 |
| 工具注册与执行 | `logagent/ai/tools.py` | 工具声明、参数校验、异步调用、有界执行和事件记录。 |
| 包入口 | `logagent/ai/__init__.py` | 导出 `AIService`，不在导入时创建网络客户端。 |

系统提示词、模型和工具引用属于可复用 `AIConfig`；每次分析的 `prompt` 属于 `AnalysisTask`。后续 Agent 可以复用本服务和工具注册表，不需要伪造 Workflow session。

## 2. 技术选型（ADR）

## 3. 接口契约

### 3.1 公共服务

```python
class AIService:
    def validate(self, config: AIConfig) -> None: ...

    async def execute(
        self, config: AIConfig, prompt: str, input_text: str,
        *, task_id: str, context=None,
    ) -> AnalysisResult: ...
```

`validate()` 不请求远程模型；它验证提供方、模型、URL、超时、参数和工具引用。错误使用 `LogAgentError(code, message, details)`，`details` 包含相对于 `AIConfig` 的字段路径。Workflow/API 再加资源或分析任务路径。

`execute()` 使用调用方传入的独立配置副本。执行前再次校验，配置异常属于调用错误；网络、模型协议或工具执行失败转为分析结果。外部 `CancelledError` 向上传递，由 Workflow 记录取消，不把取消伪装成成功或普通模型失败。

HTTP 客户端通过构造参数注入，并由应用 lifespan 创建和关闭。AI 不增加与根契约重复的启动入口；测试可注入 Mock transport 和工具注册表。

### 3.2 AIConfig 与 JSON

```json
{
  "id": "review_model",
  "provider": "http",
  "model": "configured-chat-model",
  "base_url": "https://model.example.invalid/v1",
  "api_key_env": "LOGAGENT_MODEL_KEY",
  "system_prompt": "只根据给定资料分析，并明确不确定之处。",
  "model_options": {"reasoning_effort": "low"},
  "tools": [],
  "timeout": 60
}
```

`provider` 首版取 `mock/http`；`model` 为非空字符串；`timeout` 为正的有限秒数。HTTP 提供方要求有效的 HTTP(S) `base_url`，在其末尾拼接 `/chat/completions`。`mock` 不需要地址和凭据；空 `model_options` 即可离线工作。

`api_key_env` 保存环境变量名或为空。保存配置时检查名称格式，执行时解析；指定但不存在时返回可修正的凭据错误。解析出的值只用于请求，不进入快照、异常、日志或测试产物。

输入模型拒绝未知顶层字段；`model_options` 允许提供方的 JSON 扩展，但必须验证以下边界：

- 在配置和嵌套模型参数中拒绝 `temperature`、`top_k`，不在默认请求中生成这些参数。
- 禁止模型参数覆盖服务控制的 `model/messages/tools/tool_choice/stream`，以及地址、认证和超时配置。
- 拒绝不可 JSON 序列化的值、非有限数值；提供方不支持的其余参数返回明确模型错误，不静默删除。
- `tools` 为已注册工具名称列表，不允许未知名称或重复名称；不会从配置文本执行代码。

### 3.3 提示词与提供方协议

用户消息通过字面替换 `{input}` 生成，每处占位符都接收同一份完整 `input_text`。没有该占位符时，使用 `prompt + "\n\n" + input_text`；不调用会解释任意 JSON 花括号的通用模板执行器。

`system_prompt` 独立生成系统消息；用户消息与系统消息不拼成一个角色。配置对象和输入字符串保持不变，分支之间不共享可变消息列表。fan-in 的输入是 Workflow 编排好的整体文本，同样经过此入口。

HTTP 请求体包含 `model`、有序 `messages`、服务生成的工具声明及有效 `model_options`；首版使用非流式响应。支持正常文本响应与兼容的 `tool_calls`，拒绝无可用输出的畸形响应，不把 HTTP 错误正文作为成功结果。

Mock 默认产生可重复的文本结果，并可在测试中注入返回值、等待和故障。并发、取消及恢复测试均可离线运行，不要求真实模型或付费调用。Mock 与 HTTP 使用相同的 `AnalysisResult` 契约。

### 3.4 工具接口与执行边界

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema，对象参数
    handler: Callable[[dict, object | None], Awaitable[object]]
# handler 接收经过 schema 校验的 arguments 和本次 context。
```

工具注册发生在装配阶段，同名注册失败；`AIConfig.tools` 只选择其中一部分。执行前同时验证工具已注册、被本次配置允许、参数可解析且符合 schema。未知工具、无效参数和重复调用 ID 不得进入实际 callable。

首版采用服务级执行预算：默认最多一轮工具调用、每次分析最多八个工具调用、单工具最多十秒、单工具返回 JSON 最多 64 KiB；总执行时间仍不得超过 `AIConfig.timeout`。这些预算由服务构造参数设置，不混入透传的 `model_options`，测试可注入更小值。

第一轮模型可以返回工具请求；服务按请求顺序执行并追加带原调用 ID 的工具结果，再请求最终文本。第二轮仍请求工具时返回预算耗尽错误，不启动无限循环。无工具分析只需一次模型请求。首版无内置任意 shell 工具。

工具错误返回结构化结果；模型可以据此完成回答，但工具事件保留失败事实。超出总时限时直接结束分析。超大结果报告超限，不截断成看似完整的数据；工具 callable 不得吞掉取消信号。

`context` 是可选执行上下文，允许携带 `session_id/workflow_id/stage` 和异步事件接收器。工具事件包含调用 ID、工具名、结果或错误、耗时；回调对象不序列化。Workflow 将可序列化事件保存在分析存档中；未来 Agent 可以使用自己的接收器。`AnalysisResult` 不额外塞入运行时回调或秘密。

### 3.5 结果、错误与时间

```json
{
  "task_id": "summary",
  "status": "success",
  "text": "本次采集结果摘要。",
  "error": null,
  "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
  "elapsed_ms": 52
}
```

`status` 为 `success/failed/timeout/cancelled`。成功时 `text` 为模型最终文本；失败和超时必须有结构化 `error`，不能返回“失败说明”充当成功分析。未提供计费用量时 `usage` 为空对象，不能伪造 token 数；`elapsed_ms` 以单调时钟计算且非负。

| 情况 | 对外结果或行为 |
| --- | --- |
| 配置或工具引用无效 | 校验异常，给出字段路径；保存或触发验证阶段即可发现。 |
| 连接失败、HTTP 非成功、响应畸形 | `failed`，保留可识别错误码与脱敏原因。 |
| 连接、请求、工具或总时限耗尽 | 按所在层保留原因；总执行超时为 `timeout`。 |
| 工具参数错误、预算耗尽 | 有界工具错误；不能隐式放宽预算或执行未注册工具。 |
| 外部取消 | 取消子调用并向上传播，由 Workflow 持久化 `cancelled`。 |

连接与单次 HTTP 请求超时均取不超过总预算的值；后续工具和最终模型请求使用剩余预算，不能每轮重新获得完整总时限。首版不自动重试模型请求；Workflow 的显式恢复可重新执行失败分支。

## 4. 异步与资源约束

AI 服务允许多个独立调用并行推进，实际分支上限由 Workflow 信号量控制。服务不持有全局会话消息历史，也不把上次工具结果混入下一次分析。

HTTP 等待采用协程；工具接口为异步，工具内部的阻塞工作须自行移交线程并设置原生超时。取消无法撤销已由远端受理的请求，但本地必须结束后续工具及模型调用。应用关闭时先停止 Workflow，再关闭共享客户端。

日志记录任务、session、提供方、耗时和错误码，不记录认证头、完整凭据或默认输出全部请求正文。模型内容和工具结果的保存范围由存档策略决定。

## 5. 验收设计

测试建议位于 `tests/test_ai.py`，只使用 Mock transport、临时环境变量和测试工具。

| 场景 | 可验证结果 |
| --- | --- |
| Mock 基本分析 | 返回确定内容、正确 `task_id` 和非负耗时。 |
| 模板与角色 | JSON 花括号保持原样；有无 `{input}` 都能完整传入输入，系统角色独立。 |
| HTTP 请求 | 地址和 body 正确，分支配置不相互污染，服务控制字段不可覆盖。 |
| 禁用参数 | 顶层和嵌套 `temperature/top_k` 均被拒绝。 |
| HTTP 故障 | 非成功码、无效 JSON、空协议结果均非 `success`。 |
| 超时与取消 | 总耗时有界，取消传递，不继续下一轮工具或模型请求。 |
| 工具校验 | 未注册、未授权名称及不合 schema 参数不触发 callable。 |
| 工具预算 | 调用 ID 被保留，超轮数、超数量和超大结果被明确拒绝。 |
| 凭据保护 | 模型可收到测试凭据，日志、结果、快照和错误中不存在其值。 |
| 并行执行 | 多个任务可同时等待，结果与对应输入、提示词严格匹配。 |

这些是待实现验收标准；未执行测试前不记为通过。

## 6. 依赖与后续接口

依赖公共 `AIConfig/AnalysisResult/LogAgentError`、异步 HTTP 客户端和工具 schema 校验。配置存储由配置模块提供；Workflow 注入快照和事件上下文，存档由 Workflow 负责。

v0.2 可新增独立 Agent 执行器，复用提供方、工具与 AIConfig，并增加显式多步预算和对话路由。当前单次分析不隐式变成对话；关联 `session_id/task_id/stage` 足够指向已保存的 Workflow 结果。YAML Toolset 属于后续能力，不在首版配置中接受未实现字段。
