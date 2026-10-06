# redesign-agent-module 实施交接

交接日期：2026-10-06。用户要求采用独立 worktree，基于最新 commit 实现，并在此时交接。当前是**结构拆分已落地、最新基线兼容已合入、最终验收未完成**；不要宣布完成或归档 change。

## 工作区与基线

| 项目 | 当前值 |
| --- | --- |
| 主工作区 | `/mnt/d/code/LogAgent`，分支 `main`；用户的未提交内容未被本实现覆盖 |
| 实现 worktree | `/mnt/d/code/LogAgent/.worktree/redesign-agent-module` |
| 实现分支 | `implement/redesign-agent-module` |
| 初始基线 | `e71341c` |
| 当前基线 | `3381e04`，已完成 rebase；该提交新增 Workflow Agent Task |
| 实现检查点 | `a5bd9fc`，`refactor(agent): checkpoint module redesign implementation`；其后的存储原语接入、测试迁移和交接文档随本次交接固定 |
| 是否合入 main | 没有 |
| OpenSpec | `openspec/changes/redesign-agent-module/`；未归档 |

`a5bd9fc` 是实施检查点；其后的存储原语接入、新增 Workflow 测试迁移、交接文档和任务状态已随本次交接固定。下一位仍应先看 `git status` 和 `git log`，确认 worktree 没有新的并行修改。不要重新 cherry-pick 子任务分支；其产物已经整合，直接 cherry-pick 会覆盖 facade 或引入旧兼容入口。

此次 rebase 保留了最新基线的 Workflow 功能，并迁移到新结构：`SessionView` 的 task/source/prompt/tool 字段、`storage/invocations.py` 的冻结 AI 配置文件、`SessionManager` 的创建/fork/source、`ResourceProvider` 的工具选择、`TurnRunner` 的输入模板/模型错误、历史 turn 查询，以及 `workflow.agent_service` 接线。数据目录仍保留原有路径，未读取真实用户数据作为夹具。

## 已有实现

- `AgentService` 已变为依赖注入 facade；session 值与 `TurnCoordinator/ActiveTurn` 的任务、锁、命令分离。保留 `model_provider` 属性代理，支持原有测试和嵌入调用方在启动后注入模型。
- `runtime/` 已提取 state/context、builder、runner、stream、recovery、sessions、turns；`tools/` 使用真实 `ToolRuntime.tool_call_id` 进入唯一 executor，沿用官方 LangGraph checkpointer。
- `context/` 提取 prompt、budget、compaction；`storage/` 提取事件、artifact、settings、binding、session/checkpoint/invocation；`workspace/` 提取文件、self view、沙箱和进程。
- `storage_primitives/` 已有 atomic、locks、digest、revision、jsonl、sqlite、paths；最新未提交修改把 EventLog、file I/O 和 workspace digest 委托到这些原语。
- 渠道 processor 已迁到 `channel/agent.py`，命令入口改成 `CommandDispatcher`；registry 指向 `agent.tools.builtin.*`；旧 flat 模块已删除。
- 前端已接入 `@langchain/vue` 的 `useStream` 和自定义 v2 `AgentServerAdapter`，迁移页面和测试，删除旧 `agentEventSource.ts`。
- `tests/fixtures/agent_pre_redesign/` 保存旧实现生成的完成、中断工具、fork、Workflow/MCP 合成数据和 SQLite checkpoint；CLI 交接夹具仍需补齐核对。

## tasks.md 的完成状态

唯一勾选清单：[tasks.md](../openspec/changes/redesign-agent-module/tasks.md)。详细决策与证据：[task.md](../openspec/changes/redesign-agent-module/tasks/2026-10-06-agent-module/task.md)。当前勾选 **14 / 22 项**：

| 已完成 | 对应实现与证据 |
| --- | --- |
| 1.1 | 调用方/registry/组合根盘点；原基线 Agent 122 项通过；重新盘点了 `3381e04` 新增 Workflow 调用方 |
| 2.1 | 七类共享原语及临时文件/SQLite/并发/依赖边界测试 |
| 2.2 | contracts、ports、ToolDeclaration 与唯一配置默认值；架构/工具注册测试 |
| 2.3 | workspace/files/views/进程/沙箱迁移，原路径、self identity、ETag 和取消测试 |
| 2.4 | EventLog、artifact、settings、binding、Sessions 与官方 checkpoint adapter；storage/primitives/legacy fixture 测试 |
| 3.2 | ToolNode → ToolRuntime → executor；真实工具执行、稳定键、异常及取消测试 |
| 3.3 | 唯一 RunnableConfig/thread 和一次 v2 图流；框架/任务所有权测试 |
| 3.5 | context prompt/budget/compaction、recovery/fork 协调；旧夹具和 context/final contract 测试 |
| 4.1 | SessionView 无 task/lock/log；turns 单独拥有准入、任务和待处理命令 |
| 4.2 | integrations 资源快照、模型租约、MCP/Workflow 适配；turn config 与 binding 测试 |
| 4.3 | 渠道 processor 与 CommandDispatcher 迁移；渠道 20 项、platform admission 5 项曾通过 |
| 4.4 | FastAPI/lifespan 复用同一 Agent/ChannelManager，初始化前登记资源；Agent API 与 lifecycle 测试 |
| 4.5 | 内置路径整体切换，默认工具引用 registry，关闭不导入和静态架构测试 |
| 4.6 | Vue SDK adapter 和页面/测试迁移；前端子分支的 24 项定向和 254 项全量测试通过，完整产物已合入 |

剩余 **8 项**为 1.2、1.3、3.1、3.4、5.1–5.4；多数已有部分代码或验证，但仍欠完整契约或最终验收。特别是 3.1、3.4 存在下述设计差距，不能勾选。

## 验证状态

以下旧基线结果只证明当时的实现，不代替 rebase 后验收：

| 检查 | 已确认结果 / 范围 |
| --- | --- |
| `e71341c` 原 Agent 基线 | 122 passed |
| 重设计 Agent | 138 passed，20.45 秒；随后架构/contracts/stores/primitives 定向 36 passed |
| Agent API | 旧基线 10 passed，包含真实 HTTP/SSE 的断开/回放和文件条件写入；最新 Agent API + SSE 为 14 passed |
| 渠道 / lifecycle | 旧基线 Agent 渠道 20 passed、platform admission 5 passed、通用 lifecycle 21 passed；最新 Agent 渠道为 13 passed |
| lint / 构建 | 旧基线 `ruff check src tests`、Python wheel/sdist、前端 typecheck/build、architecture 均通过；最新 lint/build 结果见下方 |
| 最终前端子任务 | 24 项定向、254 项全量、typecheck/build/architecture/改动文件格式通过；全仓格式有 15 个未修改文件偏差 |
| OpenSpec | 当时严格校验通过；`skip_specs`，未归档 |

注意：最初整合只复制了前端的早期版本，出现 11 项失败和 hydration rejection；后续已将 `207dbfc` 的**最终 15 文件产物**通过补丁同步到主实现，不能使用早期测试结果判断现有代码。

当前基线 `3381e04` 的交接前验证已确认退出码 0（临时日志不属于长期交付）：

- `/tmp/logagent-redesign-handoff-agent.log`：`tests/agent tests/storage_primitives`，**176 passed**，40.74 秒。
- `/tmp/logagent-redesign-handoff-workflow.log`：Workflow Agent Task integration/tasks，**25 passed**，28.94 秒。
- `/tmp/logagent-redesign-handoff-frontend.log`：adapter/stream/protocol/view 四个 Agent 测试文件，**24 passed**。Vue 的 `inject()` 在部分 scope 测试中仍有 warning，无未处理 rejection。
- `/tmp/logagent-redesign-handoff-lifecycle.log`：`tests/lifecycle/test_agent_channels.py`，**13 passed**，38.95 秒。
- `/tmp/logagent-redesign-handoff-interaction.log`：Agent API + SSE，**14 passed**，21.68 秒。
- `ruff check src tests`：通过；三个迁移测试的 import 排序已修复。
- Python wheel/sdist 构建：通过，产物在 `/tmp/logagent-agent-module-dist-final/`。
- 前端 typecheck、生产 build：通过；build 转换 4209 个模块，49.45 秒，退出码 0；依赖 Zod 的注释位置产生 Rollup warning。
- OpenSpec 严格校验：通过；归档未执行。

后端全目录组合命令以前超过 60 秒而被终止，必须分批执行，不能记录为通过。Feishu 测试也出现超时；SMTP 的 0.1 秒预算场景并发运行时曾偶发失败，单独四个拒绝/断连场景重跑通过，未经根因核对不要修改无关通知行为。

## 剩余差距与下一步

按下面顺序继续，先恢复当前状态，不从头做一遍：

1. **从已通过的最新基线继续。** 上面五批回归、lint 和构建已通过，无需原样重复。新增 Workflow 测试已改为调用组合根 factory，旧 session 的 MCP binding 断言改为 BindingStore。先 review 交接检查点与 `git status`，按剩余工作选择有针对性的检查；新的失败必须明确记录。
2. **完成 LangGraph 结构契约（3.1、3.4）。** 当前 `runtime/builder.py` 每轮 `create_agent` 编译，runner 每轮 `create_graph`；普通 turn 的 topology 还没有复用。append/compact 使用 ContextMiddleware 的更新字典/`jump_to`，还没有明确的 `Command` 边界。`AgentState` 仅 messages/turn/branch；`Runtime`、`stream_writer` 等目标接口需要逐条审查，保留已有 `model/tools` checkpoint 节点和旧 thread 兼容。不要为了凑目录创建空 nodes/interrupts 文件，也不要人为添加用户确认中断。
3. **最终审查注入与恢复边界（5.3）。** `ports.py` 有部分未真正用在消费方的协议，`ModelLease.lease` 返回类型也需与实际 async context manager 核对，删除未用协议并补准确注解。最新 Workflow task 的 AI invocation 恢复、fork、来源只注入一次、显式工具集，以及缺 checkpoint/未知副作用测试已在 176/25 项回归内通过。SessionStore 的终态过滤已按最新基线改为明确事件类型，不能回退到 `startswith('turn.')`，否则 `turn.resources` 会破坏重启状态。
4. **核对夹具和疑点（1.2、1.3）。** 补 CLI 来源的旧数据证据；逐项核对 references §4 的 MCP 执行类别、已完成工具结果修复、损坏尾部和路径映射边界，将已有偏差与此次回归分开记录。遵守现有业务规范，不借重构更改权限和恢复规则。
5. **完成最终验收（5.1–5.4）。** `interaction/fastapi/agent.py` 现在是 Agent factory，由现有生命周期调用；完整 FastAPI 目录迁移属于独立 change，不另建永久应用资源图。补其余 interaction/channel/lifecycle/Workflow 验证；随职责迁移测试目录，修正跨测试 import 和架构测试 SOURCE 路径。当前 typecheck/build 和 Python build 已通过，后续代码变更后再执行受影响检查；继续完成实际 app/lifespan/HTTP/SSE 与 Vue adapter 的发送、工具结果、stop、重连、fork、卸载、重启 smoke。最后 review diff、扫描旧导入、严格 OpenSpec 校验，补 tasks 证据。

建议先执行：

```bash
cd /mnt/d/code/LogAgent/.worktree/redesign-agent-module
rtk git status --short
rtk git log --oneline -3
rtk proxy cat /tmp/logagent-redesign-handoff-agent.log
rtk proxy cat /tmp/logagent-redesign-handoff-workflow.log
rtk proxy cat /tmp/logagent-redesign-handoff-frontend.log
rtk proxy cat /tmp/logagent-redesign-handoff-lifecycle.log
rtk proxy cat /tmp/logagent-redesign-handoff-interaction.log
rtk git show --stat HEAD
```

## 协作与修改限制

- 中文汇报；shell 使用 `rtk`；手工改文件用 `apply_patch`；每批后端单测 60 秒硬超时。
- 保持 `proposal.md` 和 `design.md` 原文；设计调整须用户授权。实施记录写详细 `task.md`，进度只有根 `tasks.md` 一份。
- 主仓库仍有人在修改。当前基线 `3381e04` 已纳入；下一位如发现新的 commit，先保存本 worktree 改动再做显式整合，不能从主工作区复制未提交文件。
- 子 agent 的工具消息在本环境会显示 `gAAAA...` 密文，无法直接读取；最终文字和 `/tmp/*handoff.md` 可读。最近 follow-up 没有可靠地产生新的实现，继续工作时优先看文件和 git，不等待密文消息。
- 不自动合并 main，不宣称外部真实模型/MCP provider 联调通过，不在验收未完成时归档本 change。
