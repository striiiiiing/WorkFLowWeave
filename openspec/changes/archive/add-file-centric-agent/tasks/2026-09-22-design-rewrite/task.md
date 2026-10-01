# Agent 设计重写记录

## 变更范围

2026-09-22 用户明确要求连同 `design.md` 一起重新审阅和重写，因为上一版修改可能存在自相矛盾或遗漏。此前用户已经要求先提交现有修改，因此重写前已创建基线提交 `39fac21`。本任务只记录本次设计重写的依据和新增决策，不把旧实施任务标记为已完成。

本次重写涉及：

- 重新统一 `design.md` 的 Agent 图、工具、文件、并发、沙箱、压缩、恢复和 API 契约；
- 同步 `frontend.md`，消除前端行为与后端边界的冲突；
- 保留 `proposal.md` 作为已提交的变更目标；
- 不修改旧 `tasks.md`，以免把旧设计的实施记录和新设计混为一份事实来源。

## 采用的关键决策

| 决策 | 依据 |
| --- | --- |
| 使用 `create_agent`、ToolNode 和官方 middleware | 用户要求整体基于 LangGraph；已核验 LangChain 1.4.2 的公开 middleware hook 和工具循环，避免自写 ReAct 图。 |
| 在 `before_model` 安全边界处理 compact/append | 运行中的 `update_state` 会与同一 thread 的 checkpoint 写入产生竞态；未配对的 AI tool call 不能被压缩拆开。 |
| 工具固定为 plugin/read/write/grep/shell | 用户要求少量工具；Collector 通过一个网关按 list/schema/call 发现，Collector 数量不增加顶层 Schema。 |
| Collector 每次 call 只执行一次 | 复用 `CollectorManager` 的单次语义；不在 Agent 层加入重采、后台队列或隐式重试。 |
| Channel 不加入自由选择的 plugin 网关 | Channel 有会话路由和投递不确定状态；模型任意选择发送目标会绕开既有路由和幂等边界。 |
| 调度器按工作区分片 | 所有会话共享一个进程级读写锁会阻塞互不相关的工作区；同一工作区仍需写独占，因为 Memory、AGENTS 和文件确实共享。 |
| 使用普通文件承载记忆和历史 | 用户明确要求 Linux 式可读文件、Agent 自己写 Memory 和 History；不增加专用记忆工具或向量索引。 |
| `AGENTS.md` 在 turn 开始固定 | 保持 prompt 前缀稳定；活动 turn 修改不改变已经捕获的 system prompt，从下一轮或新分支生效。 |
| 沙箱默认开启、网络默认关闭 | bubblewrap 提供简单的单次 Shell 边界；缺少隔离能力必须返回 `sandbox_unavailable`，不能静默降级。关闭沙箱明确表示按服务进程权限运行。 |
| 默认上下文 `C=200,000`、90% 触发、保留最近 40,000 | 这是本项目的可配置默认，参考用户提出的高容量模型和 Claude Code 的自动压缩思路；不宣称上游固定阈值。 |
| 复用 `SummarizationMiddleware` 且 `trim_tokens_to_summarize=None` | 已核验官方默认输入裁剪为 4,000 tokens；关闭该裁剪，避免摘要前丢失早期消息，同时对摘要模型容量做显式检查。 |
| 前端首版自建 SSE adapter | 已核验 `@langchain/vue` 的 `useStream` 需要 LangGraph Streaming Protocol v2；普通 FastAPI SSE 不能直接传入。未来可实现 `AgentServerAdapter` 后再接官方 transport。 |

## 新增实施关注点

- 需要验证 middleware 的 `before_model`/`after_model` 跳转声明、ToolNode 的未配对工具消息边界和 command queue 的 continuation。
- 需要验证工作区级锁在多个会话和多个工作区下的并发行为，尤其是读 semaphore 的获取顺序和取消释放。
- 需要验证事件 JSONL 的 `started` 占用、Artifact 提交、checkpoint 更新和外部副作用之间的崩溃窗口；未知结果不得重做。
- 需要验证 SSE 回放与实时订阅在同一 cursor 边界无缝衔接，前端按事件 ID 去重。
- 需要验证官方 Vue 包的固定版本与 `AgentServerAdapter` 类型；在后端未实现协议前不把普通 SSE 宣称为官方组件兼容。

## 验证

- `design.md`、`frontend.md`、`references.md` 的相对链接和 Markdown 结构需通过 OpenSpec 严格校验。
- 文档 diff 需通过 `git diff --check`。
- 本任务不宣称 Agent 功能已实现；产品代码、后端集成、真实沙箱和浏览器烟测仍由后续实施任务验收。
