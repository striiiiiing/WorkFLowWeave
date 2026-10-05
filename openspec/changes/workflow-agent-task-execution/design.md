# 设计

## 1. Task 级执行配置

`AnalysisTask` 增加：

```python
agent_mode: bool = False
agent_tools: list[str] | None = None
```

`FanInConfig` 在允许 Agent 汇总时使用同样的两个字段。它们描述当前分析任务或汇总任务，不属于 Analyze 子图。

- `agent_mode=false`：调用现有 `AIService.execute()`。
- `agent_mode=true`：调用 Workflow 到 Agent 的适配入口。
- `agent_tools=None`：本 Task 继承 Agent 当前已启用的全部工具。
- `agent_tools=[]`：本 Task 不允许使用工具。
- 非空列表：本 Task 只允许使用列出的已启用工具。

现有 `ai`、`model`、`system_prompt`、`input_prompt` 和 `user_prompt` 保持原语义。高级模式只控制前端是否显示工具选择，不增加后端的高级模式字段。Task 独立 system_prompt/input_prompt 优先，未设置时继承 Workflow 共享字段；user_prompt 为 Task 自己的必填差异。普通与 Agent 分析均采用三层消息。

## 2. 统一 Workflow 来源会话接口

保留 `POST /agents/sessions`，请求根据字段自动派生 Session 类型：

```text
没有 workflow_session_id                         -> standalone
只有 workflow_session_id                         -> workflow_continue
workflow_session_id + task_id                    -> workflow_subtask
```

不要求客户端重复提交 `session_kind`；服务端在创建事件和返回 DTO 中写入派生后的类型。

统一来源解析器负责读取 Workflow 结果：

```python
resolve_workflow_source(workflow_session_id, task_id=None)
```

- `task_id=None` 读取 Workflow 的最终汇总，供继续会话使用。
- `task_id=<analysis id>` 读取指定分析任务的结果，供分析子任务使用。
- `task_id="final"` 表示汇总结果，使用已有输出 ID，避免新增 stage 字段。

`final` 是来源查询接口的保留值。旧配置中同名分析任务继续可执行，其 Agent 过程可通过 `agent_session_id` 打开；该分析任务不通过 `task_id=final` 查询来源，以免与汇总发生歧义。

继续会话不传 Task 覆盖参数，沿用默认模型、全部工具和现有继续提示词。子任务传入该 Task 的模型、提示词和工具白名单。两种会话都创建新的 Agent Session，不继承另一个 Agent Session 的聊天消息。

Workflow 正在执行 Task 时，由执行适配器直接传入本次已准备好的输入正文；此时 Task 结果尚未生成，不能读取自身结果。用户从历史结果创建会话时，才由统一来源解析器按 Session ID 和 Task ID 读取存档。

## 3. Agent Session 数据

`AgentSession`、`session.created` 和会话 DTO 增加：

```python
session_kind: Literal["standalone", "workflow_continue", "workflow_subtask"]
workflow_task_id: str | None
```

已有 `workflow_session_id` 继续作为来源运行 ID。老会话读取时根据历史字段推导类型：没有 Workflow 来源为 `standalone`，有来源且没有 Task ID 为 `workflow_continue`。

子任务的 Agent Session 是可追溯的正常会话。Workflow 只等待第一次 turn 的结果并保存 `agent_session_id`；之后用户发送的消息继续写入该 Agent Session，不更新父 Workflow 的 `AnalysisResult`。

## 4. Agent 调用覆盖

创建 Workflow 子任务时向 Agent Service 传入一次调用覆盖：

```python
AgentInvocation(
    model=task.model,
    system_prompt=effective_system_prompt,
    input_prompt=effective_input_prompt,
    user_prompt=task.user_prompt,
    tools=task.agent_tools,
)
```

Agent 继续保留工作区运行规则、会话身份和现有上下文处理；Workflow 的系统提示词作为本次 Task 的提示词输入。输入模板使用现有 `{input}` 规则，只在首轮注入来源正文。后续用户消息继续走 Agent 现有消息接口。

Agent 在本次 turn 捕获资源时过滤工具声明，不修改全局工具启用状态。模型和 AI 配置使用 Workflow 启动时解析出的快照，避免运行中配置变化影响本次任务。

## 5. Workflow 执行适配

分析节点和汇总节点共用一个适配函数：

```text
if task.agent_mode is false:
    AIService.execute(...)
else:
    create Workflow Agent Session
    submit one turn
    wait for turn result
    return AnalysisResult(text, status, agent_session_id)
```

适配函数负责：

- 传递 Task 自己的模型和提示词；
- 传递 Task 自己的工具选择；
- 记录稳定的 Workflow 运行、阶段和 Task 身份；
- 将 Agent turn 的完成、失败、取消转换成 `AnalysisResult`；
- 在 Workflow 取消时调用 Agent 的 `cancel()`，等待工具和会话清理；
- 使用确定性的 operation ID 识别“子会话已完成但父图尚未落盘”的重试，避免重复执行工具。

本地 operation ID 由 Workflow Session ID 和实际条目/阶段存档键派生；显式重做对应的存档键包含 attempt generation，不引入源端 execution_epoch。普通恢复沿用原 ID；用户明确重做某阶段时产生新轮次和新 Agent Session。已完成首轮从 Agent 事件恢复结果；中断且没有完成事实的首轮明确报错，不自动重新执行不确定的工具操作。

`AnalysisResult` 增加可选 `agent_session_id`，用于报告页面打开 Agent 过程；没有 Agent 执行时保持为空。

## 6. 前端

分析任务卡和汇总卡保留现有模型选择与提示词输入，增加一个“使用 Agent”勾选项。高级模式下，仅在当前 Task 内显示工具选择；不显示 Analyze 子图级工具配置。

运行报告使用 `agent_session_id` 和 Task ID 打开已有 Agent 会话，直接复用 `useAgentSession`、SSE、`AgentTranscript` 和工具调用组件。普通 Agent Session、Workflow 继续会话和 Workflow 子任务通过 `session_kind` 分组或过滤。

## 7. 恢复边界

本变更不要求 Workflow 父图恢复到 Agent turn 的内部节点。Agent Session 自己保留既有检查点，因此用户可以打开子任务继续对话；这种后续对话不参与父 Workflow 恢复或结果重算。

如果将来要求父图和 Agent 内部节点原子恢复，再单独评估把 Agent 图嵌入 Workflow 子图的方案，不在本变更中提前引入。

## 8. 验证重点

- 同一 Workflow 中 LLM Task 与 Agent Task 混合并行执行。
- 每个 Task 使用自己的模型、提示词和工具白名单。
- 汇总 Agent 使用自己的 FanIn 配置，不继承 Analyze 子图配置。
- 三种 Session 类型创建、恢复、列表和前端展示。
- Workflow 取消能清理 Agent turn 和工具。
- 子任务结果含 Agent Session ID，用户继续子任务不会改变父 Workflow 结果。
- 旧 Workflow 和普通 Agent Session 行为保持兼容。

## 2026-10-04 契约修订

新 Agent 首轮是有效系统消息、包含 input 的 Human 消息、Task 差异 Human 消息；适配器不追加固定执行指令。Agent 汇总即使只有一个 Task 且模型相同，也使用汇总自身三层消息，永不采用单任务优化，前端不提供该按钮。历史恢复显式使用原固定首轮文本以保持请求身份；新建配置仍强制差异必填。切换 Agent 模式保留用户填写的 Prompt。详见 [修订设计](../align-workflow-prompt-contract/design.md)。
