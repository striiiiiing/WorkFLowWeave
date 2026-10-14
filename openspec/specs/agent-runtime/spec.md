# agent-runtime

## Purpose

说明文件工作区的长期记忆、会话身份、稳定指令和 checkpoint 保留规则，明确副作用未知时不自动重新执行，分支不覆盖旧历史。实现与验收证据见 Git 历史和本地分析稿；历史验证不能替代当前版本回归。

## Requirements

### Requirement: Memory and history are readable files

系统 SHALL 提供工作区根 `AGENTS.md`、按配置时区的 `Memory/YYYY-MM-DD.md`、可编辑 `History/<session>.md`、只读 Runtime、事件和 Artifact。Agent MUST 使用普通 read/write/grep 维护 Memory 和 History，不增加记忆专用工具或向量索引。活动 turn 捕获的 AGENTS 和工具定义保持稳定，修改从下一轮或新分支生效。

Runtime MUST provide a session-scoped read-only logical file `Runtime/self.json`. Its stable path MUST be included in the built-in runtime instruction so the model can discover it without knowing its own ID. Its resolution MUST use the current Agent session context, so concurrent sessions reading the same logical path receive different metadata; it MUST NOT be implemented as a shared `Runtime/current.json` file.

#### Scenario: Keep instructions stable during a turn

- **WHEN** Agent turn 已经开始后用户修改 `AGENTS.md`
- **THEN** 当前 turn 继续使用已捕获内容，下一轮或新分支才读取修改后的文件

#### Scenario: Write daily memory with ordinary files

- **WHEN** Agent 判断一条信息值得保留并调用普通 `write`
- **THEN** 内容写入配置时区对应的 `Memory/YYYY-MM-DD.md`，系统不额外创建记忆工具或自动日记

#### Scenario: Read the current session identity

- **WHEN** 两个 Agent 会话并行调用 `read("Runtime/self.json")`
- **THEN** 每个调用返回其自身的 `session_id`、`turn_id` 和 `branch_id`，不会读取或覆盖另一个会话的元数据

### Requirement: Checkpoints and side effects are retained safely

系统 SHALL 以 LangGraph thread 保存执行状态，并记录 `created_at`、`updated_at` 和 `last_checkpoint_at`。由于 SQLite saver 不能安全删除链上任意中间 checkpoint，普通压缩/分支 MUST NOT 删除中间行；整条 thread 只有在显式保留策略、过期、无活动轮次和无分支/Artifact 引用时才可清理。工具执行前后 MUST 记录稳定键和事实，未知副作用不得自动重做。

#### Scenario: Fork without editing old history

- **WHEN** 用户编辑自己的历史输入并确认 fork
- **THEN** 系统从旧 checkpoint/消息节点建立新分支，旧分支和模型输出不变

#### Scenario: Crash during a side effect

- **WHEN** 外部动作开始后服务在完成事件提交前退出
- **THEN** 会话标记 interrupted/outcome_unknown，恢复时不自动重做该工具
