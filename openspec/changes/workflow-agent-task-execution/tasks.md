# 任务

依据：[提案](proposal.md)、[设计](design.md)、[Workflow Task Agent 规范](specs/workflow-agent-tasks/spec.md) 和 [Agent Workflow Session 规范](specs/agent-workflow-sessions/spec.md)。

- [x] 1.1 扩展 `AnalysisTask`、`FanInConfig`、前端类型和默认值，增加 Task 级 `agent_mode` 与 `agent_tools`，不增加 Analyze 子图级配置。
- [x] 1.2 抽取统一 Workflow 来源解析，支持最终汇总、指定分析 Task 和保留 ID `final`。
- [x] 1.3 扩展 Agent Session 创建与持久化，派生并保存三种 `session_kind` 及 Workflow Task ID。
- [x] 1.4 让 Agent 创建入口接收本次 Task 的模型、提示词和工具过滤，继续会话保持现有默认行为。
- [x] 1.5 实现 Workflow Agent 执行适配：创建、提交、等待、取消联动、幂等重试和 `AnalysisResult.agent_session_id`。
- [x] 1.6 更新分析任务卡、汇总卡和运行报告入口，复用现有 Agent 会话和 `AgentTranscript` 展示。
- [x] 1.7 增加后端和前端定向测试：混合执行、Task 工具隔离、三类会话、来源索引、取消、子任务继续不回写。
- [x] 1.8 运行定向测试、Ruff、前端类型检查、构建、OpenSpec 严格校验和最小端到端验证。

默认值依据：`agent_mode=false` 保持所有既有 Workflow 行为；`agent_tools=null` 复用 Agent 全局启用工具，避免新增工具配置时改变现有 Agent；Workflow Session 创建请求由 `workflow_session_id` 与 `task_id` 自动派生会话类型，减少重复字段和非法组合。


## 实施与验证记录（2026-10-02）

- 完成 Task/FanIn 级配置、Agent Session 来源/类型、私有模型快照、首轮提示词复用、工具隔离、Workflow 执行适配与前端入口。没有新增 Analyze 子图级配置。
- Workflow 侧 16 项新增用例通过（分组执行）：混合任务、独立汇总、重跑身份、创建/提交/等待三处取消、失败策略、错误信息保留、旧配置、真实 AgentService + WorkflowRunner 离线集成、继续会话不回写。每次后端测试进程均使用 60 秒硬超时。
- Agent 侧 11 项新增用例通过：三类 Session、来源索引、首轮提示词、工具隔离、模型快照、重启后首轮去重和失败正文拒绝；API/channel 定向回归 33 项通过。Workflow 既有定向回归 8 项通过。
- 前端 36 项定向用例通过，类型检查、生产构建及架构检查通过。Ruff、`git diff --check` 通过。
- `npx --yes @fission-ai/openspec validate workflow-agent-task-execution --strict` 通过。未进行 archive，保留活动变更供异步审查。
- 集成使用真实图、SQLite、AgentService 和离线脚本模型；没有调用外部付费模型，也未进行浏览器人工验收。

### 已知验证限制

- Agent 广泛回归中，原有 `test_shell_uses_only_minimal_environment` 因当前 Shell 多出 `SHLVL`、`_` 环境变量失败；本变更未修改 Shell 实现。
- 前端 `workflow-model-catalog.test.ts` 的原有断言把“未保存更改”提示也当作目录错误，另跑结果为 2 通过、1 失败；保留原断言，未纳入本次修复。
- 首次整组 Workflow 恢复测试在 60 秒硬超时停止，已改为与本次关联的定向分组验证；不声明整组全通过。
- QQ 早期阶段通知出现网络连接/读取超时，最终进度通知已发送成功。

## 本地适配说明（2026-10-04）

源端实施记录仅作为历史依据；当前仓库验收以 `align-workflow-prompt-contract` 的任务及验证结果为准。


## 本地契约修订验收（2026-10-04）

Task 独立 System/Input 优先，否则继承 Workflow；Human 输入模板和差异必填。新 Agent 首轮三层消息不追加固定执行指令，汇总始终常规三层并隐藏优化选项；旧首轮恢复保留历史请求身份。前端切换 Agent 模式不生成或清空差异。实际消息、持久化、分支、旧首轮恢复与浏览器保存行为已经验证；范围和结果见 [契约修订验收](../align-workflow-prompt-contract/tasks.md)。上方 2026-10-02 源端记录及其限制为历史依据，本地默认顺序、Prompt 和恢复身份以本次修订为准。
