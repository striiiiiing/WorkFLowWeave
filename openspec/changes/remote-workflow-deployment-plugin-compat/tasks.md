# 执行任务

## 决策依据与默认值

| 决策 | 依据及理由 |
| --- | --- |
| 十个 source package 的清单 | 远端 `plugins/qwenpaw_sources/main.py` 当前注册的十个稳定 Collector 名称；一能力一目录才能验证独立停用/重载。`qwenpaw_notify` 与内置 `mock` 分开统计，避免把通知和测试能力混入来源数量。 |
| 不称为 manifest v2 | `/mnt/d/code/QwenPaw` 固定版本清单使用 `type`、`entry`、`dependencies`、`qwenpaw_version`、`meta`，没有 `manifest_version` 或 `api_version=2`；因此只称 QwenPaw-style manifest。 |
| 远端先于指标和 MCP | 用户指定顺序为 merge → 本地验收 → 远端同步；AxonHub 与真实 Agent-MCP 只有远端部署后才有有效观测对象。 |
| 15 分钟 SSE/运行观察预算 | 现有 SSE 使用 15 秒空闲心跳且普通 Workflow 运行可超过单次请求；测试只设置有界总超时并把未终态明确记为失败，不以长时间等待隐藏挂起。 |
| token 节省不设预定百分比 | 直接 JSON 与清洗 JSON 的实际长度取决于十个来源内容；仅报告成对测量结果，不把历史约 36.4% 估算当成本轮证据。 |

## 1. OpenSpec 与测试先行

- [x] 1.1 新建 proposal、四个 capability specs、design 和本任务清单；明确十个 source inventory、远端拓扑、指标口径和 Agent-MCP 绑定。
- [ ] 1.2 为清单归一、十个来源 inventory、独立 reload/禁用、远端 HTTP/SSE、AxonHub 指标和 Agent-MCP 绑定补充测试；测试先于实现变更提交。
- [ ] 1.3 运行 `openspec validate remote-workflow-deployment-plugin-compat --strict --no-interactive`、`git diff --check`，并在本任务记录真实结果。

## 2. 本地 merge 前验收准备

- [ ] 2.1 复核 redesign worktree 的任务 13.1–13.6 及 intent barrier 修复，确认没有覆盖主工作区用户未提交改动。
- [ ] 2.2 记录主工作区 dirty 文件，采用可恢复方式保存后将 `feat/redesign-workflow` 合并到主分支；每个冲突单独报告，不强制覆盖。

## 3. Merge 后本地验收

- [ ] 3.1 按后端 60 秒硬超时运行变更相关单测、Ruff/类型检查和构建。
- [ ] 3.2 运行 HTTP/SSE smoke 与 Playwright；随后用 Windows Tabbit、GPT-6 Luna Max 进行真实页面导航、Workflow run、snapshot 首帧、终态和离页检查。
- [ ] 3.3 对照 redesign-workflow 第 13 节更新验收证据；Tabbit runtime 关闭上下文时保持 13.8/13.9 未勾选并汇报阻塞。

## 4. 远端同步与插件迁移（本地验收通过后）

- [ ] 4.1 通过 SSH 记录 `myserver:~/opt/workflowServer` 分支、dirty 清单、监听端口、当前插件 inventory 和备份位置；不 reset/clean。
- [ ] 4.2 将清单归一层及十个 source package 作为独立提交同步；每个包仅注册一个稳定 source ID，保留 `qwenpaw_notify` channel 和公共 CLI 适配。
- [ ] 4.3 更新远端前端 API base 指向后端，验证 health、plugin inventory、Workflow 配置/触发、SSE snapshot/terminal、历史查询和所有十个来源能力。
- [ ] 4.4 验证 Workflow 绑定 Agent 携带精确 MCP 集合；覆盖 MCP 缺失/禁用/越权时不发送的失败路径。
- [ ] 4.5 从 AxonHub 读取同一时间窗口的 input/output/cache counters，完成缓存率和直接 JSON/紧凑 JSON 成对 token 报告；字段缺失则明确报告不可用。
- [ ] 4.6 运行远端定向测试、Ruff/构建和一次真实无副作用或测试渠道 Workflow；保存 session/请求 ID，不打印凭据，并对每个大改动 commit。

## 5. 代码审查与交付

- [ ] 5.1 审查 diff：无隐式 manifest 映射、静默 fallback、凭据/运行数据同步、重复插件 owner 或第二套事件存储。
- [ ] 5.2 在本任务记录本地 merge、远端 commit、十个 source inventory、SSE/Agent-MCP 证据及 AxonHub 原始计数摘要；只有全部验收条件满足才宣布完成。
