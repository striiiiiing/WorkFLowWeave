# Agent 其他指令 UX 审计与修正

状态：已完成。用户要求继续检查其他指令的 UX，选中文件为 `src/workflowweave/plugins/channel/README.md`。

## 依据、范围与性质

依据本 change 的 [proposal](../../proposal.md)、[design](../../design.md) §2/§5/§7（唯一命令分类、查询不切换、stop 独立通道、命令只报告自身结果），[实例绑定设计](../../../bind-duplex-channel-conversations/design.md) §3/§4，以及 [Agent 设计](../../../redesign-agent-module/design.md) §4.2（空闲 append 为普通轮次、compact 的安全边界、workflow 仅读历史结果）。此前 `/resume` 修正见 [独立任务](../2026-10-10-resume-command-ux/task.md)。

这次是共享命令契约的结构性修正：参数规则和切换判断在 Agent 命令边界统一表达，ChannelManager 消费同一判断。不修改 proposal/design、前端或模型执行语义，不新增命令/别名/默认模型/自动重试。

## 已确认缺口与实施决策

| 指令/入口 | 缺口 | 修正与依据 |
| --- | --- | --- |
| `/new`、`/stop`、`/compact` | 多余参数静默忽略，误输 `/stop other` 仍可能停止当前任务 | 明确无参用法；在操作分类阶段拒绝多余参数，停止准入前验证，防止输入错误产生副作用 |
| `/append` | 空参数只收到“消息不能为空”，未指出用法 | 命令边界给出 `/append <补充内容>`；保留正文额外空格、多行，以及空闲开启新轮次/运行中安全边界语义 |
| `/fork`、`/workflow <id>` | 多余空白保留为目标 ID；多个参数无明确用法 | 仅规范化 ID 参数，拒绝多个 ID；fork 保留已完成轮次和精确 checkpoint 的真实限制 |
| `/workflow` | 无参历史列表被当作切换屏障；平台收到原始 JSON | 只有导入具体结果才是切换；无参沿现有 limit=100 查询，不改默认值；平台展示名称/状态/运行 ID 与可复制的 `/workflow <id>`，空历史明确说明 |
| `/stop` | 审计初步怀疑停止会推进绑定版本；复核发现 stop 已走独立分支，不调用 bind_instance | 保持现有实现，增加停止不改变绑定快照的回归断言；不为未复现问题新增改绑 gate |
| compact、append 完成回复 | 仅“轮次状态 completed/命令状态 completed”，失败未提供原错误 | 依据真实终态/command 事件给出动作名称和结果；保留错误 code/message，不能把受理或取消说成成功 |
| 未绑定/未知指令 | “需要 session/未知命令”无下一步 | 提示 `/new`、`/resume` 和支持的用法，保留结构化错误码 |
| 渠道 README | 没有指令表或空闲/运行中区别；无参 resume 未同步 | 增加现有指令语法、效果和限制；说明 Web 菜单本地动作 `/file`、`/settings`、`/clear` 并非平台命令 |

## 检查发现但不在本轮编辑边界

Web 页面 `AgentPage.vue` 没有处理后端新增的 `kind=sessions`，API 类型也没有该分支；手动发送无参 `/resume` 会消费输入却不展示列表，菜单 `/resume` 则打开既有 drawer。这是前端契约缺口，不能将后端 HTTP 测试声称为页面验证；本 change 明确限制前端编辑，记录实际限制。

## 任务与验证

- [x] 统一语法/参数提示与前置验证，区分 workflow 查询和导入屏障。
- [x] 验证停止保持现有绑定；补动作完成/失败文本。
- [x] 更新渠道 README，补逐项命令矩阵。
- [x] 针对性单测（每批 timeout 60s）、Ruff、OpenSpec strict、diff review、wheel 构建、最小实际应用烟测。

验证结果在实施后记录，未执行的外部平台联调和前端验证不得记为通过。

实现补充：无参 compact 的运行时返回轮次终态，未返回是否实际生成摘要，因此使用“上下文整理已完成”而不声称一定发生压缩。运行中的 compact 使用 command 事件的 `compacted` 区分“已压缩”和“无需压缩”；失败仅投影公开结构化 code/message，普通异常仍记录日志并展示类型，避免原始异常带出敏感输入。停止返回的是取消完成后的会话文档，不能从历史 status 推断本次是否取消了任务，统一报告“停止请求已处理，当前没有活动轮次”。这些选择依据 `agent/runtime/turns.py.cancel/wait/compact`、`agent/runtime/runner.py` 的真实返回和 `errors.py` 的公开错误契约。

## 实施与验证记录（2026-10-10）

- `AgentCommand.operation()` 统一执行参数校验与 ID trim；Manager 在计算 priority、switch 和 stop gate 前调用同一操作分类。`/stop wrong` 不会成为 stop 请求；实测活动轮次保持运行。
- `/workflow` 无参保持查询，使用既有 `SessionView.list_sessions(limit=100)`；具体运行 ID 才导入结果并切换绑定。`/resume` 无参仍列出 Agent 历史且不改绑定。
- `BaseConversationChannel` 依据实际 turn/command 终态投影 compact、append 的动作结果和公开错误；Web 与平台渠道都传递操作名。停止仍走已有独立 stop 分支，不调用 `bind_instance`。
- 渠道 README 增加命令语法、空闲/运行中语义、错误下一步、Workflow 查询/导入区别，并记录 Web 手动无参 `/resume` 仍受前端 `kind=sessions` 未接入限制。
- 通过：`timeout 60s .venv/bin/python -m pytest -q tests/agent/test_commands.py tests/channel/test_resume_command.py`（22 项）；`tests/channel/test_command_ux.py` 与 invalid stop 回归（3 项）；compact/fork/stop/Workflow 既有回归（6 项）；Ruff；`openspec validate redesign-agent-channel-manager --strict --no-interactive`；`git diff --check`。
- 待验证：真实 QQ/飞书/Telegram/微信平台联调未执行；前端手动 `/resume` 列表展示未执行且本 change 禁止修改前端。
