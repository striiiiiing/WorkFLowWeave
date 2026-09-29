# 执行任务

## 决策依据与默认值

| 决策 | 依据及理由 |
| --- | --- |
| 十个 source package 的清单 | 远端 `plugins/qwenpaw_sources/main.py` 当前注册的十个稳定 Collector 名称；一能力一目录才能验证独立停用/重载。`qwenpaw_notify` 与内置 `mock` 分开统计，避免把通知和测试能力混入来源数量。 |
| 不称为 manifest v2 | `/mnt/d/code/QwenPaw` 固定版本清单使用 `type`、`entry`、`dependencies`、`qwenpaw_version`、`meta`，没有 `manifest_version` 或 `api_version=2`；因此只称 QwenPaw-style manifest。LogAgent v1 的目录名与 ID 不一致仍按既有 owner 规则兼容。 |
| 远端先于指标和 MCP | 用户指定顺序为 merge → 本地验收 → 远端同步；AxonHub 与真实 Agent-MCP 只有远端部署后才有有效观测对象。 |
| 15 分钟 SSE/运行观察预算 | 现有 SSE 使用 15 秒空闲心跳且普通 Workflow 运行可超过单次请求；测试只设置有界总超时并把未终态明确记为失败，不以长时间等待隐藏挂起。 |
| token 节省不设预定百分比 | 直接 JSON 与清洗 JSON 的实际长度取决于十个来源内容；仅报告成对测量结果，不把历史约 36.4% 估算当成本轮证据。 |

## 1. OpenSpec 与测试先行

- [x] 1.1 新建 proposal、四个 capability specs、design 和本任务清单；明确十个 source inventory、远端拓扑、指标口径和 Agent-MCP 绑定。
- [x] 1.2 为清单归一、十个来源 inventory、独立 reload/禁用、远端 HTTP/SSE、AxonHub 指标和 Agent-MCP 绑定补充测试；测试先于实现变更提交。初始缺口以收集错误暴露：四个契约模块尚不存在；补齐后新测试 22 项通过，现有配置/工具/启动回归 62 项通过（合计 84 passed，11.97s；60 秒硬超时）。
- [x] 1.3 运行 `openspec validate remote-workflow-deployment-plugin-compat --strict --no-interactive`、`git diff --check`；均通过。Ruff 目标文件检查通过。

## 2. 本地 merge 前验收准备

- [x] 2.1 复核 redesign worktree 的任务 13.1–13.6 及 intent barrier 修复；保留主工作区用户未提交的 `data-v4/`、`node_modules/`、`src/logagent/lifecycle/.idea/`，未覆盖或回滚。
- [x] 2.2 已将 `feat/redesign-workflow` 合并到 `refactor/frontend-architecture`：merge commit `d7674f7`，intent barrier 修复随后以 `d99e122` 记录；合并前后均未使用 reset/clean。

## 3. Merge 后本地验收

- [x] 3.1 按后端 60 秒硬超时拆分运行变更相关回归：配置/调用 20 passed；MCP/CLI 2 passed；intent/receipt、checkpoint 与恢复关键场景 4 passed；进程强退四个场景分别通过；SessionStore 关键并发/幂等 7 passed；collection history 15 passed。`ruff check src tests` 通过；前端 typecheck、architecture check、build 通过；前端 Vitest 49 文件/243 测试通过。
- [x] 3.2 隔离 Playwright 全量 17/17 通过；本地临时后端 14301 + 前端 3000 的 live smoke 1/1 通过；HTTP/SSE API smoke 200。旧 Collector E2E fixture 已迁移为 MCP/CLI `call` 契约，并补充 CLI raw 结果无业务 `count` 断言。
- [x] 3.3 对照 redesign-workflow 第 13 节更新证据：自动化 13.8/13.9 相关部分通过；Windows Tabbit 使用 GPT-6 Luna Max 导航后两次复现 `Target page, context or browser has been closed`，未收到真实 Workflow run 的 SSE `snapshot`/终态/离页证据，因此 13.8、13.9 继续未勾选，不将 runtime 阻塞伪报为通过。

## 4. 远端同步与插件迁移（本地验收通过后）

- [x] 4.1 通过 SSH 记录 `myserver:~/opt/workflowServer` 分支、dirty 清单、监听端口、当前插件 inventory 和备份位置；不 reset/clean。
- [x] 4.2 将清单归一层及十个 source package 作为独立提交同步；每个包仅注册一个稳定 source ID，保留 `qwenpaw_notify` channel 和公共 CLI 适配。
- [ ] 4.3 更新远端前端 API base 指向后端，验证 health、plugin inventory、Workflow 配置/触发、SSE snapshot/terminal、历史查询和所有十个来源能力。
- [ ] 4.4 验证 Workflow 绑定 Agent 携带精确 MCP 集合；覆盖 MCP 缺失/禁用/越权时不发送的失败路径。
- [ ] 4.5 从 AxonHub 读取同一时间窗口的 input/output/cache counters，完成缓存率和直接 JSON/紧凑 JSON 成对 token 报告；字段缺失则明确报告不可用。
- [ ] 4.6 运行远端定向测试、Ruff/构建和一次真实无副作用或测试渠道 Workflow；保存 session/请求 ID，不打印凭据，并对每个大改动 commit。

## 5. 代码审查与交付

- [ ] 5.1 审查 diff：无隐式 manifest 映射、静默 fallback、凭据/运行数据同步、重复插件 owner 或第二套事件存储。
- [ ] 5.2 在本任务记录本地 merge、远端 commit、十个 source inventory、SSE/Agent-MCP 证据及 AxonHub 原始计数摘要；只有全部验收条件满足才宣布完成。

## 本轮本地验收补记（2026-09-29）

- Playwright 旧 Collector 契约已从 `frontend/tests/e2e/frontend.spec.ts`、`resources.spec.ts`、`live.spec.ts` 清理，改测 CLI shell source、MCP/CLI editor、raw stdout/stderr、固定版本正文和无业务 count。
- 发现并修复 `ResourceStore` 对带 `SourceConfig.call` 的 workflow override 仍进入 Collector capability 校验的问题；call 形式由 `SourceConfig.call` 自身校验，回归测试为 `test_cli_source_workflow_limits_override_skips_collector_capability_check`。
- 统一补齐旧 Collector 快照的显式兼容边界：公开 `CollectorInvocation` 不再解引用空 `call`，`SessionView.mcp_binding` 与健康诊断会跳过非 MCP 来源；新增回归后 MCP/SessionStore 28 项、采集/配置 48 项、生命周期筛选 12 项、MCP/CLI 与 overrides 19 项均通过。
- 未启动远端 SSH、插件迁移或 AxonHub 查询；这些项目严格留待本地验收收口后执行。Live smoke 首次无服务时的 `ECONNREFUSED 127.0.0.1:3000` 是环境前置缺失，启动可控本地链路后已通过 1/1。

## 远端插件同步与本地前端复验补记（2026-09-29）

- 远端原 dirty 清单已保存到 `/tmp/workflowServer-remote-sync-20260929-142144`，并建立可恢复分支 `backup/remote-plugin-sync-20260929-142144`；未 reset、clean 或覆盖用户文件。远端原有未提交文件仍保持 dirty 状态。
- 远端提交 `76e50c1` 拆出十个独立 QwenPaw source package，并把当前紧凑 JSON/CLI 适配提取到 `src/logagent/qwenpaw`；`6d1cd6d` 修正新文件权限。旧 `qwenpaw_sources` 只作为显式 `logagent_legacy` 回滚副本，不发布重复能力；`qwenpaw_notify` 仍是独立 channel。
- 远端定向测试 `tests/qwenpaw/test_split_plugins.py tests/qwenpaw/test_adapters.py tests/config/test_config.py`：79 passed；目标文件 Ruff 通过。远端服务重启后 `GET /api/health`、`GET /api/plugins`、`GET /api/sources`、`GET /api/workflows` 和 `POST /api/reload?scope=plugins` 均 HTTP 200，health 为 ready；plugin inventory 共 25 项，其中十个 source ID 与 owner 一一对应，另有两个 `qwenpaw_notify` channel，未发布旧聚合能力。十个 daily source 的 `call-schema` 查询全部 200（10/10），但未执行带外部 CLI/通知副作用的采集。
- 远端前端 systemd 服务实际监听 `13002`，`API_TARGET=http://127.0.0.1:4300`，经 `13002/api/health|plugins|workflows` 代理验证 HTTP 200；`3000` 属于同机其他 Karakeep 服务，未误判为本项目入口。
- 本地前端复验：`npm run typecheck`、`npm run architecture:check`、`npm run build` 通过；Vitest 49 files/243 tests passed；Playwright 17/17 passed（54.9s）。
- 仍未勾选 4.3–4.6：本轮只验证了远端健康、inventory、资源/Workflow 查询和插件 reload，尚未在远端实际触发 Workflow 并取得 SSE `snapshot`/终态/历史证据，也未完成远端 Agent-MCP 精确绑定和 AxonHub 原始缓存/token 计数；这些不是本轮已完成项。
