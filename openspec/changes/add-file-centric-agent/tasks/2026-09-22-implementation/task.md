# Agent 实施与审核记录

## 授权与基线

- 2026-09-22 用户授权实施已写明的 Agent/前端设计，要求先 commit，再写 task.md，随后执行，每个完成点单独 commit。
- 实施前基线：`36d8f96`，包含此前工作树的业务、测试和 OpenSpec 改动；`master.key`、`master.key.initialized` 保留本地，未提交。该提交是工作快照，不等同于通过功能验收。
- 基线 staged whitespace 检查发现前序 `frontendFix/tasks/2026-09-21-frontend-architecture-review/task.md` 的 EOF 空行；保留原状，不混入 Agent 实施。
- 仓库 post-commit 钩子自动推送 workflow，基线推送因 non-fast-forward 拒绝，本地提交有效。后续使用钩子已有的 `SKIP_WORKFLOW_PUSH=1`，本任务仅创建本地提交。
- 权威依据：[proposal](../../proposal.md)、[design](../../design.md)、[frontend](../../frontend.md)、[任务索引及默认值](../../tasks.md)。本轮不修改 proposal/design/frontend；若实现发现必须改变设计，先提出具体差异。
- 产品代码、任务记录由主代理编写。用户最新修订：上下文依赖少的独立只读分析/测试使用 `gpt-5.5`、推理 `xhigh`；其他允许委派的复杂任务仅在能够明确指定 `gpt-6-astra`、推理 `xhigh` 时派发。此前已启动的依赖审计使用原授权的 Astra xhigh；不追溯改写执行事实。子代理不得写产品代码、设计或任务文档，不提交。当前续接已恢复指定模型派发能力，独立生命周期回归审计按最新授权使用 GPT-5.5 xhigh。

## 结构性判断与不变量

这是新增跨模块执行契约，不能以局部聊天端点或自写 ReAct 代替设计。公共配置解析、模型租约、插件发现分别复用唯一入口；新增代码只承担 Agent 会话、文件、预算和工具包装。

审核先对照 design/frontend 的用户行为，再对照下列任务及验证证据。每项完成提交同时更新本记录；未实际验证的条目保持未完成。各项依赖顺序为 A → B → C → D → E → F，独立只读调查和测试准备可并行。

## 任务与验收

### A. 依赖兼容（对应 2.1）

- [x] A1 在独立虚拟环境解析并锁定 LangChain 1.x、LangGraph 1.x、匹配 checkpoint/sqlite、aiorwlock；提交 pyproject.toml 和 uv.lock。
- [x] A2 先用旧依赖建立恢复证据，再在现有 Workflow 数据库副本验证新版本读取；不打开原库进行迁移。
- [x] A3 回归父子图、取消、恢复与通知去重；核实 create_agent、异步工具包装、摘要中间件公开 API 和 `trim_tokens_to_summarize=None`。

预期改动：pyproject.toml、uv.lock、必要的兼容修正及 tests/workflow。升级失败必须查清旧库/框架语义差异，不以重置数据库通过检查。

### B. 公共接入与插件（对应 2.2–2.4）

- [x] B1 在 AI 模块抽取共享模型 lease，支持显式 streaming/输出限制，文本分析继续原契约，凭据解析/连接/错误脱敏不重复实现。
- [x] B2 从 ResourceStore 抽出共享调用解析；新增 call_options_schema，保留引用、类型和合法调用默认值，拒绝实例层覆盖。
- [x] B3 Registry/配置/owners/只读视图/发现报告/API/前端 DTO 全面增加 tool kind；五个内置工具懒加载，enabled 仅存插件配置。
- [x] B4 logs/history/mock 声明 read，其他未声明 Collector 为 exclusive，Channel 固定 exclusive；验证禁用不导入、冲突和事务回滚。

预期改动：src/logagent/{ai,config,schema.py,models.py,protocols.py,lifecycle}、前端插件类型以及对应测试。保留旧 Collector/Channel 内置启停语义。

### C. 文件与工具边界（对应 3.1、3.3–3.4、4.1–4.4）

- [x] C1 唯一 WorkspaceBackend 支持目录句柄安全访问、只读映射、分页、hash/If-Match、原子覆盖及精确替换；Runtime/self.json 由会话视图解析。
- [x] C2 注册 plugin/read/write/grep/shell；网关复用实例快照与 Manager 单次调用，不重复 Schema 或发送逻辑。
- [x] C3 共享 aiorwlock 与读 semaphore；排队、取消、超时均可见，读 4/写 1且写与读互斥；调度器已提供给后续 AgentService 复用。
- [x] C4 bubblewrap 单次进程、最小环境、只读事实挂载、网络开关、进程树清理；实际隔离不可用时明确失败，关闭沙箱使用固定最小环境。
- [x] C5 工具完整输出文件化、预览预算和 16 MiB 超量失败；AGENTS 常驻、Memory 按时区、History 笔记与事实分离。

预期改动：agent/{workspace,sandbox,tools,gateway}.py、内置 tool 插件及测试。数值沿用 tasks.md 已列理由：200 行、50 命中、20 目录项、60 秒 Shell、约 2000-token 预览；不新增隐含硬上限。

### D. 会话、图与持久一致性（对应 3.2、5.4–5.6）

- [ ] D1 AgentService 持有后台轮任务、每会话单轮、request_id 幂等；每轮固定资源/插件同代快照。
- [ ] D2 使用 create_agent 与独立 SQLite checkpointer，整轮持有模型租约；连接断开不取消运行，显式取消释放工具与租约。
- [ ] D3 JSONL 原子占用/started fsync/结果提交；稳定调用键复用、同键异参冲突、活动键共享任务、发送前记账。
- [ ] D4 重启标记 interrupted/outcome_unknown，不重做旧副作用；补齐工具消息后接收新消息，checkpoint 缺失/损坏明确不可继续。
- [ ] D5 lifecycle 装配、关停、插件 reload 在活动 Agent 轮时 busy；资源更新只影响下一轮。

预期改动：agent/{events,service,graph}.py、lifecycle 和恢复测试。事实来自 JSONL，checkpoint 保存框架上下文，笔记不能反向修改状态。

### E. 上下文与压缩（对应 5.1–5.3）

- [ ] E1 每次请求重载 AGENTS、计算 system/tools 和当前模型预算；未知窗口必须显式配置，实际输出上限与预留一致。
- [ ] E2 动态委托官方 SummarizationMiddleware，关闭 4000-token 输入裁剪；独立摘要租约、容量/输出限制/timeout，错误传播。
- [ ] E3 一次请求至多一次逻辑压缩，摘要后再次检查；验证长历史、超大消息、摘要失败、工具成组、常驻规则与旧文件保留。
- [ ] E4 主模型无活动默认 300 秒，总 timeout 沿用 AIConfig；增量发布后失败不得重试拼接，工具不自动重试。

预期改动：agent/context.py、配置模型、AI 共享入口与测试。C/R/P/H/B、80% 触发、20% 保留、min(4096,5%B) 摘要预算完全来自 design §8，不冒充模型实际 usage。

### F. HTTP、SSE、前端与最终验收（对应 6、7）

- [ ] F1 独立 /api/agents 会话、消息、取消、手动压缩、文件、配置、工具 DTO；明确 409、If-Match 和 request_id 冲突。
- [ ] F2 持久序号 SSE、回放/实时无缝续传、慢客户端不阻塞执行、心跳不算模型活动。
- [ ] F3 /agents 两栏聊天与按需工具/文件/设置抽屉，复用 Markdown、报告、useQuery/useAsyncTask；新增单个导航。
- [ ] F4 工具开关沿用插件配置与 reload；显示真实沙箱/并发/未知发送状态、上下文估算、压缩摘要、文件冲突保留草稿。
- [ ] F5 前端单测、类型检查、构建；临时目录与假模型的真实后端/浏览器 SSE 烟测、窄屏、停止、重连、冲突，不连接真实渠道。
- [ ] F6 后端定向回归、静态检查、构建、旧 Workflow 回归、OpenSpec 严格验证与 diff 审查。

## 验证与提交规则

- 后端每批测试使用 `timeout 60s`；按定向单测 → 静态/类型 → 构建 → 最小烟测执行。
- 检查具有行为意义：副作用只执行一次、互斥无重叠、恢复不重放、摘要输入不丢失、前端续传不重复和冲突不覆盖。
- 每个已完成里程碑提交实现与证据。若拆成更小提交，在此新增实际边界，不提前勾选更大的未完项。
- 审查重点：重复逻辑/第二事实来源、过度 gate、吞错、静默降级、禁用绕过、竞态、重复发送、凭据泄露和与设计未说明的偏离。

## 执行记录

- 已完成：提交实施前基线，并在任何业务实现之前建立本记录。
- A 已完成（依赖由外部新增提交 `119e486` 收录，保留该提交，不重复提交相同变更）。锁定 langchain 1.4.2、core 1.6.4、langgraph 1.2.12、prebuilt 1.1.0、checkpoint 4.2.0、sqlite 3.1.1、aiorwlock 1.5.1；新环境 `/tmp/logagent-agent-implementation-venv`，原 `.venv` 仍保留旧版本供交叉验证。
- 旧/新环境 Workflow 恢复、进程退出、生命周期 39 项各通过（47.75s / 24.94s）；主代理额外按两批验证 recovery/lifecycle/interval/availability 40 项、integration/overrides/disabled/session 44 项，旧新均通过。最初合并批次 60s 超时，已拆批而非放宽时限。
- 真实旧库含 WAL，只复制库与日志后对副本备份；原文件 size/mtime/SHA256 不变。新旧解码 78 checkpoints、231 writes、10 namespaces 完全一致，摘要 `aef6c876035156948b6f52837b8ca84d7337b8f6b0c62c4d03d7a32219e26dea`。
- 旧解释器生成 crash-analysis/crash-notify/crash-archive 后新解释器恢复均通过；采集不重复、已完成分析不重复、未知发送保留 delivery_uncertain 且只继续下一目标。证据脚本 `/tmp/logagent-cross-version.py`，副本 `/tmp/logagent-db-audit-rb7qhm8j`。
- 可持续回归固化为 `tests/agent/test_framework_contracts.py`：3 passed（0.54s）；验证完整摘要输入、未知工具异常传播、pending 工具补齐消息并通过公开 aupdate_state 清理后不重放。ruff 通过，uv build 成功，OpenSpec strict 有效。
- 框架版本差异的实现依据：1.4.2 middleware 还会读取历史 AI usage 触发摘要，因此应用先按本轮预算判断是否委托；官方摘要内部 with_retry 重试所有 Exception，必须由总 timeout 覆盖，确定性容量错误在委托前校验。向 middleware 传消息副本，避免失败时它补 ID 改动原状态。不改框架私有方法。
- 尚未完成：B–F。

- B1 完成：AIService.lease 与文本 execute 共用 _model_lease/ChannelManager/凭据入口；OpenAIChannel 显式 streaming 与 max_completion_tokens，移除其他重复输出限制键且不改输入配置。模型上游错误脱敏，工具/存储异常原样传播，租约覆盖调用方整个上下文。19 项定向测试通过（5.07s），包括流式 tools HTTP payload、输出限制、连接关闭取消、凭据脱敏、Workflow 分析回归；ruff 和 diff --check 通过。

- B2 完成：config/calls.py 抽取来源模板/覆盖与渠道覆盖，Workflow 原调用路径切换到公共函数；ResourceStore.invocation_snapshot 在同一锁内捕获启用实例和模型。call_options_schema 保留定义并重定位本地引用，只暴露调用属性与非凭据默认值，固定值解除 required，跨字段约束仍由原完整 Schema 校验。47 项配置/Schema/Workflow 覆盖测试通过（8.63s），ruff 与构建通过。

- C 的细化约定：History 下单层 `.md` 为可写笔记，子目录映射运行事实并只读，避免尚未创建的会话目录被工具抢先伪造。文件读取/写入使用目录句柄和 O_NOFOLLOW；线程内文件操作在取消时先完成再释放统一调度锁，避免后台写入越过独占窗口。主模型输出预留默认 4096 tokens（可配置），用于首版文本问答和工具参数的单次输出；与真实 provider 限制同步，并在模型容量不足时要求调整，不代表模型窗口。

- B3/B4 完成：工具声明与注册事务、owner 冲突、只读视图、generation、发现/API/前端 DTO 已贯通；五内置工具先查 enabled 后导入，logs/history/mock 声明 read，其余 Collector 默认 exclusive。184 项插件/配置/契约/HTTP/生命周期定向测试通过（12.22s），ruff、前端类型与构建、Python 构建通过。生命周期旧测试预期纯正文但未关闭默认 include_counts；仅使该测试显式声明 False，完整 lifecycle 20 项通过，未改变业务默认。

- C4 进程清理决策：仅 killpg 无法回收 Shell 中调用 setsid 后脱离原进程组的后台任务。单次 Shell 使用独立的 Linux subreaper 监督进程；主服务取消先通知监督进程，监督进程杀死并回收所有后代后才退出，不在主服务设置全局 subreaper，也不影响 Workflow 的子进程。该辅助进程只承接本次命令，不构成后台 Shell 会话。

- C 批次完成：修正 Shell 使用 `sh -c`，避免登录 Shell 从宿主 profile 注入环境变量；`WorkspaceBackend` 增加 `Runtime/self.json` 会话作用域逻辑映射、Runtime/Sessions 只读目录和不可搜索/写入约束。新增并通过 self 映射隔离测试；Agent 定向测试 49 项通过，ruff 与 diff-check 通过。
