# Model 重构决策与实施证据

依据：[proposal](../../proposal.md)、[design](../../design.md)、[references](../../references.md)。唯一实现进度在根 [tasks.md](../../tasks.md)，本文件记录决策和证据。

## 1. 范围纠正

初稿误把用户的 Models 理解为整个 Modules，提出迁移 API、UI、Composable 和页面。用户随后明确：API 在 API 层，组件在组件层，先按业务垂直分层，再在业务内部细分模型。本次按这一明确纠正重写本 change 的规划，不修改历史 change，不迁移 Model 以外的目录。

正确目标是 `agents/model/{session,runtime,workspace}`、`resources/model/{source,mcp,ai,channel}`、`workflows/model/{create,run,history}`。Workflow 三类模型放在一个业务文件夹；其他层仍在原目录。

## 2. 决策与依据

| 决策 | 依据 | 约束 |
| --- | --- | --- |
| 只重构 Model | 用户最新范围纠正 | API/UI/Composable/pages 只做必要导入或类型签名适配，不重排或改行为 |
| 业务优先、内部再拆模型 | 用户明确分层顺序 | 不建 agents/session/api 或 workflows/run/ui；子域都在 model 内 |
| Workflow Model 聚合 | 用户要求创建、运行、历史同目录 | runs/model 归入 workflows/model，runs 消费层保留原位 |
| Workspace 是用户操作模型 | 用户明确 Agent 不通过前端操作工作区 | 只迁移 AgentFile/分页/条件写入类型，不迁移后端工具或注册执行器 |
| 保持独立 Resource | 用户要求及现有 workflows → resources 关系 | SourceConfig 与 Resource DTO 仍由资源模型唯一拥有 |
| Source 的调用与参数细分 | resources/model/types.ts、resources.ts | 用值类型组合 SourceConfig，不拆出独立资源或多份编辑草稿 |
| Setter 不新增能力 | 当前前端只有历史字段；后端 calls/migrations | 仅兼容类型，有真实代码才建文件，不造新 CRUD 或隐式迁移 |
| 纯模型出口 | 现有 model purity、module direction 规则 | 在现有检查器中窄放行 runs → workflows/model/public，不放开 API/UI 深层依赖 |
| SDK 兼容而非合并 | 用户选中交接 065701c，主线与交接 stream 有差异 | 本 change 不迁移或重建 stream/adapter，不要求合并后端分支 |

## 3. 默认值与保持理由

| 项目 | 来源/处理 | 理由 |
| --- | --- | --- |
| Resource 默认值 | 保持 resources.ts 的 Source/MCP timeout 60s、AI timeout 600s/retries 5、Channel timeout 30s | 只将工厂按资源类型提取，不借模型拆分调参 |
| Workflow 默认值 | 保持 defaults.ts：agent_mode=false、agent_tools=null、single_task_optimization=true 等原对象 | 字段与当前用户配置/运行契约一致，按默认对象对比验证 |
| 调度、备份、输入 token 配置 | 保持现有工厂/backup/actions 的值及 null 语义 | Model 层是原值唯一归属，不新增自动补值 |
| 文件和运行 API | 请求字段、ETag、Session version/epoch 原样 | 模型路径变化不改变 HTTP/SSE 契约 |
| 状态拥有者 | 原 Composable 和 SDK 保持不变 | Model 仅纯函数/值对象，不新建 mutable store 或消息/运行状态副本 |
| URL 与组件目录 | 保持 /workflows、/runs、/agents 和现有 ui/pages | 当前任务不涉及这些层，API/UI 只改模型导入 |

## 4. 规划验证与实施记录

规划交付时为文档；当时 16 项实现任务均未开始。没有执行前端迁移、消费者改动、构建或应用测试，不宣称目标目录已经落地。

已通过 OpenSpec CLI 创建独立 change，读取 proposal/design/tasks 的 artifact 指令。`openspec list --specs` 返回 `No specs found`；纯模型重构使用 `skip_specs: true`，不虚构能力规范。

初稿的 strict/status 和链接检查曾通过，但只验证初稿格式，不能代替范围纠正后的检查。本次纠正后的实际结果：

- `openspec validate redesign-frontend-modules --strict --no-interactive`：退出码 0，CLI 明确接受 `skip_specs` 的零增量。
- `openspec status --change redesign-frontend-modules --json`：退出码 0，proposal/design/tasks 为 done、specs 为 skipped、规划齐备；这不表示代码实现完成。
- Python 3 文档检查：6 份 Markdown、41 个本地链接、16 项未开始任务，链接存在、代码围栏、行尾空白和任务编号检查均通过。
- `git diff --check`：退出码 0；新增未跟踪文档另由上述 Python 检查覆盖。

所选交接 worktree 读取时 HEAD 为 065701c 且干净；未修改或整合它。读取 RecallLoom 技能后未发现 sidecar，本次不初始化记忆目录。未修改既有 design/proposal、后端、SDK 或用户未提交文件，未 commit/apply/archive。

## 5. 实施交接

展示澄清：用户追问 Model 子模块为何出现 API。实际现状中 api/model/ui 为业务模块下同级目录，Model 内没有 API；初稿错误已撤回。修订后的 design 目标树仅展示三个业务的 model 子目录，外部 API/组件消费模型的箭头不表示它们属于模型。此项只澄清表达，未扩大重构范围或修改任何实现。

1. 先读 design 的范围与目录树，再按根 tasks 选择当前实际实施基线。
2. 类型/纯函数迁移与消费者导入更新同批完成，保留原 API、组件、控制器和页面位置。
3. 若实现发现必须重构消费层行为，则记录原因并重新确认设计范围；不能把它混入必要导入适配。
4. 把命令、退出码和字段/defaults 对比结果追加在本文件；仅全部实现和验证完成后 archive。


## 6. 2026-10-06 worktree 实施

用户已明确授权“采用 worktree 进行重构”。实施 worktree 为 `.worktree/redesign-frontend-models`，分支 `implement/redesign-frontend-models`，基线 `7ab1429`。本次沿用已纠正的 proposal/design，不更改设计决策；主工作区已有未提交的 Workflow 提示词相关修改，本 worktree 从提交基线创建，未把这些修改夹带进来。

选中 Agent 交接描述的是 SDK 分支；实施基线仍采用现有 Agent SSE/command API。依据 design §1、§3、§9，仅迁移 DTO 和纯函数，保留本基线的事件协议、transport、状态拥有者和后端；没有合并 SDK 分支。基线已有的 agent_mode、agent_tools、single_task_optimization、来源续接字段和历史兼容字段原样保留。

### 6.1 类型所有权与路径映射

| 旧模型/定义 | 当前唯一归属 | 消费者适配 |
| --- | --- | --- |
| agents/model/types：AgentSession、AgentModel | agents/model/session/types、models | 业务内 model/public 或同域精确文件 |
| agents/model/types：ContextBudget、AgentEvent、AgentTool、AgentConfig/Settings、TurnAccepted | agents/model/runtime/types | API/Composable/UI 保持原位置 |
| agents/model/events、sessionProjection、transcript | agents/model/runtime/同名文件 | SSE 生命周期仍在 api/composables |
| agents/model/sessionKind | agents/model/session/sessionKind | Sidebar 只更新引用 |
| agents/model/types：AgentFile | agents/model/workspace/types | 用户文件编辑和条件写入仍由现有 API/Composable 处理 |
| Workflow 续接输入的来源 ID/模型 | agents/model/workflow-handoff | agentsApi.create 只引用字段类型，未复制结果正文 |
| resources/model/types：SourceConfig/SourceCall/SourceOverride/gateway | resources/model/source/{definition,call,parameters,overrides} | 单一 Source editor 草稿和保存目标不变 |
| resources/model/types：collector/setters/template | resources/model/source/setters | 只提取真实旧字段，没有 Setter API 或新资源 |
| resources/model/types：MCP/AI/Channel | resources/model/{mcp,ai,channel}/types | 每类 defaults 各自唯一构造 |
| resources/model/resources | resources/model/catalog + 各类 defaults + credential + source/definition | createResource 仅组合工厂；凭据 schema 投影仍为纯函数 |
| resources/model/mcpImport、sourceFiltering、forms | resources/model/mcp/import、source/{filtering,forms} | 现有组件导入适配 |
| workflows/model/types/defaults/actions/validation/backup/sourceUsage/cronPresets | workflows/model/create；各阶段配置与 defaults 位于 stages | 顶层 createWorkflow 组合采集、分析、通知、备份默认值 |
| runs/model/types：WorkflowStage/SessionStatus/Artifact/Phase/Session/Progress | workflows/model/shared/types | run/history 共同引用；DTO 无第二份定义 |
| runs/model/session、progress | workflows/model/run/{session,progress} | runs 消费层只从 Workflow model/public 引用 |
| runsApi 的 ResumeOptions/RecoveryQuery；RecoveryAvailability | workflows/model/run/recovery | 只提取值类型，HTTP 方法和路径不变 |
| runs/model/filters、report；ReportSection | workflows/model/history/{filters,report} | 报告解析和筛选逻辑保留 |
| runsApi.SessionQuery、产物可用性标签/正文提示 | workflows/model/history/artifacts | 查询/缓存/分页仍在原 Composable |

三个业务的 model/public 是纯模型出口；原业务 public 继续提供调用方需要的模型及现有 API/UI 导出。runs/public 显式导出原运行/历史契约和已迁出的查询值类型，未把 Workflow 创建工厂暴露为 Run 能力，也未保留旧 runs/model 转导目录。

### 6.2 依赖与边界

在现有 `check-architecture.mjs` 增加窄规则：业务内消费层可引用自己的 model/public，但模型实现不可反向引用该 barrel；跨业务的 Model 只能引用纯模型出口。runs → workflows 仅放行精确 `model/public.ts`，未放行 Workflow API/UI 或深层模型。新增 type-only、动态导入、反向业务依赖、深层 API/UI、顶层 barrel、自身 barrel 正反 fixtures；原有循环与纯度 fixtures 继续执行。

依据 design §2、§4、§5，没有新增超时、重试、缓存、权限或执行策略。四类 Resource 工厂、Workflow 创建和 FanIn 的两种 reuse 默认值已通过基线差分（固定 UUID）；Source setters 只保留 collector/setters/template 三个历史字段。旧 Model 文件与绝对导入扫描无残留。

### 6.3 已完成的专项检查

- 用 TypeScript compiler 比对基线四份 types 与新模型出口：44 个旧导出类型均可双向赋值，属性名和可选性完全一致，退出码 0。
- 用 TypeScript transpile + VM 执行基线/新工厂：四类 Resource 默认值、Workflow 默认值、FanIn 空/非空 analyses 的默认值完全一致，退出码 0。
- 对比基线文件树：149 个非 Model src 文件全部保留原路径，没有新增非 Model 源文件，退出码 0。
- 旧定义/引用扫描：agents/resources/workflows 的旧根模型文件和 runs/model 实现/转导均已清除，退出码 0。

最终测试、构建和审查结果在下一节补充；专项检查不代替完整验证。

- 消费层运行逻辑审查：对 60 个改动 API/Composable/SFC 做 TypeScript 转译比较，排除 import 后 JS 逻辑一致；SFC 模板和样式字节一致，退出码 0。恢复/查询类型只从 API 移出，创建输入的字段类型引用等价。
- 受影响 Model、架构检查器/fixtures 及两个修复装配的测试通过 Prettier 检查，退出码 0；消费层原有正文格式保持基线，避免顺带格式重写。

### 6.4 基线失败与测试装配修复

从 `git archive 7ab1429 frontend` 生成临时基线副本，复用相同 node_modules，不复制主工作区未提交文件。基线 typecheck 退出码 0；完整单测为 52 文件/262 用例，50 文件与 257 用例通过，5 用例失败，退出码 1。迁移后首次完整测试复现相同 5 个失败，没有新增失败。

根因是 `WorkflowEditPage` 已要求 agentsApi/tools 注入，但 `workflow-model-catalog.test.ts` 和 `workflow-page-query.test.ts` 的 mount 装配未提供它。两处测试补齐真实注入 key 与显式 tools mock；既有断言不变，不 skip、不削弱断言，也未给生产代码加默认依赖或 fallback。这属于 design §7 消费者契约验证所需的测试装配修复。最终完整测试在这两处修复后重跑。


### 6.5 最终验证与审查

| 检查 | 实际结果 | 退出码 |
| --- | --- | --- |
| 基线 `npm run typecheck` | 通过 | 0 |
| 迁移后全量 `npm test` | 257/262 通过；剩余 5 项与基线相同的测试装配错误 | 1 |
| 补齐常规 mount 后 `npm test -- --maxWorkers=4` | 261/262 通过；独立 pending-catalog mount 仍缺 agentsApi | 1 |
| 最后补齐独立 mount；`npm test -- tests/unit/workflow-model-catalog.test.ts tests/unit/workflow-page-query.test.ts --maxWorkers=2` | 两文件 5/5 通过，全部既有失败得到复验 | 0 |
| `npm run typecheck` | 通过 | 0 |
| `npm run architecture:check` | 200 个源文件、44 个正反 fixtures 通过 | 0 |
| 受影响 Model/规则/fixtures 和修复测试的 Prettier check | 通过 | 0 |
| `npm run build` | vue-tsc + Vite 生产构建成功，3790 模块，Vite 用时 44.70s | 0 |
| `openspec validate redesign-frontend-modules --strict --no-interactive` | 接受纯重构 skip_specs，零能力增量 | 0 |

最终用例证据由全量中未修改测试装配的 257 个通过用例，以及修复后定向运行的 5 个通过用例组成；**最后没有再次执行第三轮全量测试，不把最后的定向命令描述为全量命令退出码 0**。最后一次代码修改仅补齐同一测试文件第三处 mount 的注入，生产代码与已完成全量回归的实现一致。现有 Vue mount/路由/编辑/Run 消费者测试覆盖本次导入适配；没有实际服务联调，按 tasks §5.1 不额外开启后端或浏览器 smoke。

最终范围复核确认：所有改动都在授权的 Model、消费者导入/等价类型、公开出口、模型消费者测试、现有架构检查器和此 OpenSpec change 内。proposal/design 与已批准的主工作区源文档字节一致，未改设计。API/Composable 的命令和请求逻辑、SFC 模板/样式、页面/路由与后端均保持基线；没有重复 DTO/defaults、隐式 fallback、第二份状态或新增 Setter 管理功能。

16 项实施任务均已完成。change 保持活动，便于用户审查本 worktree；本次没有合并主分支或 archive。

最终 `git diff --cached --check` 退出码 0；OpenSpec apply 指令返回 `16/16 complete`、`state=all_done`。改动已暂存，便于一次审查；未创建提交。
