# 远端 Workflow 部署与插件清单兼容

## Why

本地 Workflow 前端与 `myserver:~/opt/workflowServer` 后端即将分离部署，但当前远端插件仍以旧的聚合目录和 WorkFLowWeave v1 清单存在，无法证明升级后十个 QwenPaw 来源能力仍可独立使用。现在需要把远端拓扑、插件清单迁移、AxonHub 指标和 Workflow→Agent→MCP 链路写成可重复验收的 change，避免把一次 HTTP 200 或一次模型成功误当成完整部署成功。

## What Changes

- 建立“本地前端 + 远端后端”的部署与验收契约，覆盖健康检查、Workflow 配置/运行、SSE 进度和终态查询。
- 将 QwenPaw 风格插件清单（`id/name/version/type/entry/...`）通过显式兼容层归一到 WorkFLowWeave 能力注册；保留旧 WorkFLowWeave v1 清单的迁移期读取能力，冲突或未知字段组合必须报告失败。
- 保持十个 QwenPaw 来源能力的稳定 ID 和独立启停/重载语义：`qwenpaw_memos`、`qwenpaw_flomo`、`qwenpaw_halo`、`qwenpaw_karakeep`、`qwenpaw_siyuan`、`qwenpaw_tencent_docs`、`qwenpaw_activity`、`qwenpaw_codex`、`qwenpaw_claude`、`qwenpaw_dida`。十个 source package 是本 change 的数量口径；`qwenpaw_notify` 是单独的 channel package，内置 `mock` 不计入这十个来源。
- 增加成对的直接 JSON 与紧凑 JSON token 测量，以及 AxonHub 缓存命中/未命中读取；没有当前部署数据时不得声称节省比例或缓存率。
- 验证 Workflow 绑定的 Agent 只携带该绑定声明的 MCP，远端运行结果和诊断可追溯实际携带的 MCP 身份。

## Capabilities

### New Capabilities

- `remote-deployment`：本地前端连接远端 Workflow 后端并完成健康、运行、SSE 与终态验收。
- `plugin-manifest-compat`：QwenPaw 风格与 WorkFLowWeave v1 插件清单的显式归一、拒绝和十个来源能力清单。
- `telemetry-token-budget`：AxonHub 缓存指标及成对 JSON token 对比的测量口径。
- `workflow-agent-mcp`：Workflow 绑定 Agent 与指定 MCP 的运行时隔离和可观察性。

### Modified Capabilities

无。本 change 新增部署与兼容验收契约，不修改已同步主规范中的既有能力要求。

## Impact

影响 `src/workflowweave/config` 的清单解析/注册边界、远端 `workflowServer` 的插件目录和部署脚本、Workflow/Agent 运行查询、前端 API base 配置及验收测试。指标读取依赖远端 AxonHub 的现有观测接口；凭据、数据库、日志和未提交用户改动不进入 Git 或同步包。
