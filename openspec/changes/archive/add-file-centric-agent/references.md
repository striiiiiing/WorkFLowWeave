# 设计依据与核验记录

核验日期：2026-09-22。以下资料用于取舍和任务依据；上游版本会变化，实施仍以锁文件、固定源码和测试为准。外部产品的阈值不当作本项目固定限制。

## 1. 当前项目与锁文件

| 证据 | 结论 |
| --- | --- |
| `src/workflowweave/config/registry.py`、`config/views.py`、`models.py` | 当前注册事务、Schema 捕获、owner 和禁用不导入可扩展到 `kind=tool`。 |
| `src/workflowweave/schema.py`、`config/normalize.py`、`config/store.py` | 统一复用 Schema、默认值、Setter、凭据和路径校验；Agent 不复制调用解析。 |
| `src/workflowweave/collection/manager.py`、`channel/manager.py` | Collector/Channel 都是单次 Manager 调用；Channel 路由和 delivery_uncertain 不应被模型工具绕开。 |
| `src/workflowweave/ai/`、`workflow/`、`lifecycle/` | 模型租约、Workflow checkpoint 和应用生命周期已有边界，Agent 需通过公共入口接入。 |
| `uv.lock` | 当前记录为 `langchain 1.4.2`、`langchain-core 1.6.4`、`langgraph 1.2.12`、`langgraph-checkpoint 4.2.0`、`langgraph-checkpoint-sqlite 3.1.1`、`aiorwlock 1.5.1`。实施以实际锁文件为准。 |

## 2. LangGraph/LangChain

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 说明 thread checkpoint 用于短期记忆、恢复、time travel 和容错；它不等于业务历史文件。
- [LangGraph `Pregel.update_state` 源码](https://raw.githubusercontent.com/langchain-ai/langgraph/49cce0c/libs/langgraph/langgraph/pregel/main.py) 支持从历史 checkpoint 建立 update 分支，适合 `/fork`，旧 checkpoint 不被原地修改。
- [`BaseCheckpointSaver`](https://raw.githubusercontent.com/langchain-ai/langgraph/f55e772/libs/checkpoint/langgraph/checkpoint/base/__init__.py) 的公开契约包含 `delete_thread`、`delete_for_runs`、`copy_thread`、`prune`；这些是契约，不代表每个 saver 都实现。
- [`AsyncSqliteSaver 3.1.1`](https://raw.githubusercontent.com/langchain-ai/langgraph/b2926a0/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py) 可列出、读取和删除整个 thread，但未提供可安全依赖的逐 checkpoint prune/delete-for-runs 实现。官方 DeltaChannel 说明也警告删除祖先会破坏状态重建，因此本设计保留链并按整条 thread 生命周期清理。
- [`create_agent`](https://reference.langchain.com/python/langchain/agents/factory/create_agent)、[ToolNode](https://reference.langchain.com/python/langgraph/prebuilt/langgraph/prebuilt/tool_node/ToolNode) 和 [SummarizationMiddleware](https://reference.langchain.com/python/langchain/agents/middleware/SummarizationMiddleware) 提供现成模型/工具循环、并发工具分发和摘要钩子。摘要源码说明默认 `trim_tokens_to_summarize=4000`，可显式设为 `None`；本设计采用后者。
- [LangGraph Send](https://reference.langchain.com/python/langgraph/types/Send) 是图内动态任务分发，不是浏览器 push；SSE 仍由应用接口提供。

## 3. Claude Code、Codex 与 Pi

- [Claude Code 工作方式](https://code.claude.com/docs/en/how-claude-code-works.md)、[Memory](https://code.claude.com/docs/en/memory.md)、[Sessions](https://code.claude.com/docs/en/sessions.md)、[Context window](https://code.claude.com/docs/en/context-window.md) 和 [Sandboxing](https://code.claude.com/docs/en/sandboxing.md) 支持以下借鉴：对话 JSONL、指令/记忆文件分层、自动压缩、工具输出管理、文件/网络隔离。Claude 的压缩阈值随模型和部署变化，本项目 200k/90% 是自己的默认。
- [Claude prompt caching](https://code.claude.com/docs/en/prompt-caching.md) 说明缓存按请求前缀精确匹配；工具定义、系统提示和常驻文件加载顺序变化会使前缀失效。因此 Agent 在 turn 内固定工具 generation 和 AGENTS 内容。
- [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md) 说明指令在会话开始构造，而不是每轮随意改变；[Codex worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees.md) 说明真正的并行编辑依赖独立工作区。首版仍是单一工作区，故使用工作区级写独占。
- [Codex sandbox](https://learn.chatgpt.com/docs/sandboxing.md) 将文件和网络边界作为独立配置层；本设计只取其简单可关闭的边界，不实现审批和域名策略。
- [Pi 会话 README](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent)、[会话管理](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/src/core/session-manager.ts) 采用 JSONL `id/parentId` 树；[压缩实现](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/src/core/compaction/compaction.ts) 保留原始历史、以投影摘要继续模型上下文，并保持 tool call/result 配对。设计借鉴这一文件分支模型，不移植 Pi 全栈。

## 4. LangGraph Vue 前端

- 官方 JavaScript 参考提供 [`@langchain/vue`](https://reference.langchain.com/javascript/langchain-vue) 的 `useStream`、消息和工具调用组合，以及 [`@langchain/langgraph-sdk`](https://github.com/langchain-ai/langgraphjs/tree/main/libs/sdk)；它们面向 LangGraph Agent Streaming Protocol。
- 现有 FastAPI 自建 SSE 不能直接声称与官方 Vue 组件兼容。若后续实现官方协议，可参考 [custom transport](https://github.com/langchain-ai/langgraphjs/blob/main/libs/sdk-react/docs/custom-transport.md) 和 `HttpAgentServerAdapter`；首版保留小型 Vue SSE 适配，避免迁移页面。

## 5. 沙箱、锁与输出

- [bubblewrap README](https://github.com/containers/bubblewrap/blob/main/README.md) 明确它是隔离构造工具而非完整安全策略；挂载、网络命名空间和环境过滤必须由调用方指定。
- [aiorwlock README](https://github.com/aio-libs/aiorwlock) 提供多个 reader 并发、writer 独占的锁原语；本设计只在实际工作区工具操作期间持锁。
- Codex 公开提示词资料（[prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)）支持短工具说明、并行独立读取和文件/命令结果按需展开；Responses 专用 compaction 不作为本 Chat 模型的通用接口。
