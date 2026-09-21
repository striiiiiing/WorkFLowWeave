# 设计依据与核验记录

核验日期：2026-09-21。外部资料读取了页面正文或官方源码，不以搜索摘要代替依据。上游 main/master 会变化，实施时以选定版本源码、锁文件与测试为准；本文不把上游最新接口误称为仓库已安装能力。

## 1. 当前项目

以下路径相对仓库根目录，是本设计的现状证据；新增文件位置见 design.md，不代表已实现。

| 证据 | 结论 |
| --- | --- |
| `src/logagent/config/registry.py`、`config/views.py`、`models.py` | 当前只注册 collector/channel；注册事务、Schema 捕获、owner 和禁用不导入可复用。工具 kind 需要扩展。 |
| `src/logagent/schema.py`、`config/normalize.py`、`config/store.py` | 2020-12 Schema、默认值、Setter 展开、凭据/路径注解与调用层覆盖已有实现；Agent 应共用。 |
| `src/logagent/collection/manager.py`、`protocols.py` | collect 是单次、有超时和结构化结果的调用，Workflow 空结果策略不属于 Manager。 |
| `src/logagent/channel/manager.py`、`models.py:Notification` | send 单次投递但复用常驻连接；session/output 标识可由 Agent 生成；不确定投递不能当作明确失败重发。 |
| `src/logagent/ai/service.py`、`ai/channels.py`、`ai/manager.py` | 文本分析当前拒绝工具调用且关闭流式；BaseChatModel 工厂、租约和凭据生命周期已经存在。 |
| `src/logagent/workflow/graph.py`、`workflow/service.py`、`workflow/nodes.py` | LangGraph 父子图、AsyncSqliteSaver、运行任务与持久化边界已有约定。Agent 使用独立消息状态。 |
| `src/logagent/lifecycle/service.py`、`lifecycle/services.py` | Agent 装配与插件重载需要进入同一个应用生命周期，不另建插件加载链。 |
| `frontend/src/router/`、`api/client.ts`、`components/common/ParameterField.vue` | 已有导航/JSON API/Schema 表单；尚无 Agent SSE 会话。 |
| `frontend/src/components/report/`、`domain/report.ts` | 当前工作区已有报告渲染能力，设计引用当前工作区而非假定已发布版本。 |
| `openspec/README.md`、`openspec/config.yaml` | 独立需求建立新 change，根 tasks.md 为实施入口；不改写旧 proposal/design。 |

模型与工具预算的现有默认值见 `models.py`：来源 60 秒、渠道 30 秒、AI 总时限 600 秒、Workflow 读取并发 4。日志 Collector 已有最大 16 MiB 的读取规模约束，见 `collection/logs.py` 与 README；新工具输出预算参考这一量级，但并非继承同一个业务参数。

## 2. LangGraph / LangChain

### 已核验本地版本

| 包 | uv.lock 版本 |
| --- | --- |
| langchain-core | 1.6.3 |
| langchain-openai | 1.6.2 |
| langgraph | 0.6.11 |
| langgraph-prebuilt | 0.6.5 |
| langgraph-checkpoint | 2.1.2 |
| langgraph-checkpoint-sqlite | 2.0.11 |

本地可导入 Send 与 ToolNode；不能导入 `langchain.agents.create_agent`，因为没有 langchain 包。本地 ToolNode 无最新 wrap_tool_call/awrap_tool_call 构造参数。

| 官方资料 | 核验结论与采用范围 |
| --- | --- |
| [Send API](https://reference.langchain.com/python/langgraph/types/Send)、[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) | Send 为动态节点任务，适用于 fan-out，不是 Web 推送。 |
| [create_agent API](https://reference.langchain.com/python/langchain/agents/factory/create_agent)、[官方工厂源码](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/langchain_v1/langchain/agents/factory.py) | 接受 model/tools/middleware/checkpointer；当前上游内部使用 `Send("tools", [tool_call])`。选择框架已有图。 |
| [ToolNode API](https://reference.langchain.com/python/langgraph/prebuilt/ToolNode)、[官方源码](https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/prebuilt/langgraph/prebuilt/tool_node.py) | 多工具调用并行；新版本支持统一异步 wrapper，串行写规则仍须项目注入。 |
| [Middleware 协议源码](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/langchain_v1/langchain/agents/middleware/types.py) | 模型与工具 wrapper 可访问 state/runtime，工具可返回 ToolMessage/Command。 |
| [SummarizationMiddleware API](https://reference.langchain.com/python/langchain/agents/middleware/SummarizationMiddleware)、[官方源码](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/langchain_v1/langchain/agents/middleware/summarization.py) | trigger/keep 可按 tokens、fraction、messages 配置；fraction 需要模型 profile，固定小窗口并非框架硬限制。摘要裁剪应直接复用。 |
| [ToolRetryMiddleware API](https://reference.langchain.com/python/langchain/agents/middleware/ToolRetryMiddleware)、[官方源码](https://raw.githubusercontent.com/langchain-ai/langchain/master/libs/langchain_v1/langchain/agents/middleware/tool_retry.py) | 通用重试不会识别渠道/Shell 的外部副作用，首版不全局启用。 |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | checkpointer/thread 与持久化执行边界；使用同步持久化保证当前步骤落盘后再推进，不能据此承诺与文件/外部发送原子提交。 |

核验时上游 langchain 1.4.2 源码要求 langchain-core >=1.6.3,<2 与 langgraph >=1.2.11,<1.3.0；这与本地 langgraph<1 约束冲突。该信息用于证明需要成组升级，不是已经通过测试的安装建议。

摘要源码进一步核验：默认 keep 是 20 条，`trim_tokens_to_summarize=4000`，可显式设为 None 跳过输入裁剪；输入裁剪错误会取最近 15 条作为 fallback。设计采用 None 加完整摘要输入预算检查，避开该隐藏裁剪路径。摘要失败重试耗尽会抛异常；输出上限不属于中间件参数，须在摘要模型设置。system/tool 定义不包含在其 messages 计数中，且摘要模型调用不经过普通 Agent model wrapper，这两点由薄包装补齐，不复制摘要算法。

## 3. Claude Code

| 官方资料 | 采用范围 |
| --- | --- |
| [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)（已读取 [Markdown](https://code.claude.com/docs/en/how-claude-code-works.md)） | 工具循环；对话 JSONL；工具输出管理后自动摘要；完整历史和活跃上下文区别；按需加载定义。 |
| [Tools reference](https://code.claude.com/docs/en/tools-reference)（已读取 [Markdown](https://code.claude.com/docs/en/tools-reference.md)） | Read/Write/Edit/Grep/Bash 等职责分工，仅作合并后的五工具设计参考；工具集会随版本、平台变化。 |
| [Memory](https://code.claude.com/docs/en/memory)（已读取 [Markdown](https://code.claude.com/docs/en/memory.md)） | 常驻说明与模型主动维护的记忆文件区分。该产品采用 MEMORY.md 索引与主题文件，本项目遵循用户指定的按日 Memory，未照抄其行数限制。 |
| [Sandboxing](https://code.claude.com/docs/en/sandboxing)（已读取 [Markdown](https://code.claude.com/docs/en/sandboxing.md)） | Linux/WSL2 使用 bubblewrap，系统级隔离与普通工具权限不同；借鉴边界，不实现其整套代理、凭据屏蔽及审批策略。 |

Claude Code 官方说明支持自动管理上下文，但未为本项目模型提供一个可普遍照搬的自动压缩阈值。80% 触发、20% 保留均是本设计建议值。

## 4. Codex / official OpenAI documentation

| 官方资料 | 采用范围 |
| --- | --- |
| [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide) | Shell、apply_patch、文件/搜索工具及并行读的设计参考；Responses compaction 是特定接口能力，不假定当前 Chat Completions 可直接调用。 |
| [Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md) | 持续项目规则使用独立文件。Codex 自身还有目录层级、覆盖与默认读取预算；首版 Agent 只用工作区根文件以降低复杂度。 |
| [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security) | workspace 与关闭隔离的语义参考；本项目不照搬审批模式。此正文由官方 Codex sandbox 链接重定向读取。 |

## 5. 沙箱基础设施

[bubblewrap 官方说明](https://github.com/containers/bubblewrap/blob/main/README.md)（已读取 [原始文本](https://raw.githubusercontent.com/containers/bubblewrap/main/README.md)）明确指出 bubblewrap 是构造隔离环境的工具，本身不是预配置好的完整安全策略。其只读挂载、进程/网络命名空间和 new-session 可复用；挂载与可见目录必须由调用者明确配置。因此设计没有把简单 cwd 限制宣称为沙箱，也没有假设 bubblewrap 自动隔离 Python 插件。

[aiorwlock 官方说明](https://github.com/aio-libs/aiorwlock)（已读取 [README](https://raw.githubusercontent.com/aio-libs/aiorwlock/master/README.rst)）说明多个 reader 可同时持锁、writer 独占，可直接复用其 reader_lock/writer_lock。该包目前未列在本项目依赖中，实施任务明确增加并验证取消/等待语义，不声称仓库已经提供读写锁。
