# redesign-agent-module 实施交接

交接日期：2026-10-06。用户要求采用独立 worktree，基于最新 commit 实现，并在此时交接。当前是**结构拆分已落地、`3381e04` 基线兼容已合入、最终验收未完成**；主线后续提交 `7ab1429` 尚待整合，不要宣布完成或归档 change。

## 工作区与基线

| 项目 | 当前值 |
| --- | --- |
| 主工作区 | `/mnt/d/code/LogAgent`，分支 `main`；用户的未提交内容未被本实现覆盖 |
| 实现 worktree | `/mnt/d/code/LogAgent/.worktree/redesign-agent-module` |
| 实现分支 | `implement/redesign-agent-module` |
| 初始基线 | `e71341c` |
| 已整合基线 | `3381e04`，已完成 rebase；该提交新增 Workflow Agent Task |
| 主线最新提交 | `7ab1429`，新增普通 LLM 汇总单任务优化；尚未整合到本 worktree |
| 实现检查点 | `a5bd9fc`，`refactor(agent): checkpoint module redesign implementation`；其后的存储原语接入、测试迁移和交接文档随本次交接固定 |
| 原交接检查点 | `e968623`，`refactor(agent): hand off module redesign checkpoint` |
| 是否合入 main | 没有 |
| OpenSpec | `openspec/changes/redesign-agent-module/`；未归档 |

`a5bd9fc` 是实施检查点；其后的存储原语接入、新增 Workflow 测试迁移、交接文档和任务状态已随本次交接固定。下一位仍应先看 `git status` 和 `git log`，确认 worktree 没有新的并行修改。不要重新 cherry-pick 子任务分支；其产物已经整合，直接 cherry-pick 会覆盖 facade 或引入旧兼容入口。

此次 rebase 保留了最新基线的 Workflow 功能，并迁移到新结构：`SessionView` 的 task/source/prompt/tool 字段、`storage/invocations.py` 的冻结 AI 配置文件、`SessionManager` 的创建/fork/source、`ResourceProvider` 的工具选择、`TurnRunner` 的输入模板/模型错误、历史 turn 查询，以及 `workflow.agent_service` 接线。数据目录仍保留原有路径，未读取真实用户数据作为夹具。

## 主线后续 Prompt 契约补充

用户再次确认汇总模式的差异，主线已在 `7ab1429` 实现，**本重构 worktree 尚未包含该提交**：

- 普通 LLM 汇总的 `single_task_optimization` 默认开启，仅在一个分析 Task、汇总与其使用同一 AI 配置 ID 和模型、且分析成功时复用 `[Task System, Task 输入 Human, Task 差异 Human, AI(Task 回复), 汇总差异 Human]`。高级模式可以关闭；关闭或条件不满足时使用汇总自身的常规消息。
- Agent 汇总始终使用 `[汇总 System, Human(上一阶段结果), Human(汇总差异)]`，不引入分析 Task 差异、AI 回复或额外 Human；即使只有一个 Task、同模型、保存的优化开关为 true，也忽略优化。前端不显示 Agent 汇总的优化按钮。Agent 运行规则与有效系统指令仍合入同一条 System 消息。
- Task/FanIn 的 System/Input 覆盖分别优先于 Workflow 共享值；差异使用当前 Task/FanIn 自己的字段。仅输入层展开 `{input}`，系统和差异保持字面值。
- 普通 LLM 优化必须保留原分析输入到汇总完成，不能因为显式 `order` 未选 `$input` 就提前释放。优化资格和输入保留共用 `ai/prompts.py::uses_single_task_optimization`。旧 checkpoint 缺少优化字段时只在历史解码边界按关闭处理，避免改变原运行；archive 继续使用 checkpoint 原始 snapshot/fan-in，保证重放摘要不因新增默认字段改变。

实施依据仍为 `align-workflow-prompt-contract/design.md`，没有修改历史 proposal/design。主线补充记录：`openspec/changes/align-workflow-prompt-contract/tasks/2026-10-06-single-task-optimization/task.md`；此前移植范围记录也已注明后续补齐。这里的说明用于交接，不新增第二份进度勾选清单。

`7ab1429` 的主线验证：消息契约/AI Prompt/存档 25 项、相关汇总恢复 7 项、Workflow Agent 与现有集成 11 项通过；前端相关 15 项通过，含默认开关、高级模式、Agent 隐藏及关闭状态保存重开。Ruff、Prettier、typecheck、architecture、生产 build 和 OpenSpec strict 通过。较大后端组合曾触及 60 秒硬超时，随后按相关范围拆分；没有测真实供应商缓存或计费。**这些结果不能替代本重构分支整合后的验收。**

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

1. **先整合主线后续提交，再继续剩余工作。** `3381e04` 的上面五批回归、lint 和构建已通过，无需原样重复。先 review 交接检查点与 `git status`，保存新的本地修改后显式整合 `7ab1429`；不能只补文档就声称实现已同步。重点核对 AIService 消息入口、分析输入保留、旧 checkpoint 解码和不可变 archive；迁入 `tests/workflow/test_summary_prompt_contract.py` 后，将 AgentService 创建适配到重构组合根 factory，复测实际五条/三条消息和恢复。已有 Workflow 测试已改为调用组合根 factory，旧 session 的 MCP binding 断言改为 BindingStore；保留这些适配，新的失败必须明确记录。
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
- 主仓库仍有人在修改。`3381e04` 已纳入，`7ab1429` 已在主线提交但尚待本分支整合；下一位先保存本 worktree 改动，再整合已提交的变更，不能从主工作区复制未提交文件。
- 子 agent 的工具消息在本环境会显示 `gAAAA...` 密文，无法直接读取；最终文字和 `/tmp/*handoff.md` 可读。最近 follow-up 没有可靠地产生新的实现，继续工作时优先看文件和 git，不等待密文消息。
- 不自动合并 main，不宣称外部真实模型/MCP provider 联调通过，不在验收未完成时归档本 change。
