# 设计

## Context

远端 `workflowServer` 当前只有 `mock`、`qwenpaw_sources` 和 `qwenpaw_notify` 三个目录；其中 `qwenpaw_sources` 注册十个 Collector。WorkFLowWeave 本地注册器要求 `kind/api_version`，而固定版本的 QwenPaw 插件清单使用 `type`、显示元数据、依赖和 `qwenpaw_version`，没有可依据的 `manifest_version` 或 `api_version=2`。本设计因此把兼容性作为显式边界，不把“新版本”解释成未经来源支持的数值。

## Goals / Non-Goals

**Goals:**

- 在不覆盖远端未提交用户改动的前提下，把远端后端和本地前端连接拓扑变成可复验部署。
- 将十个来源能力拆成一一对应、可独立启停和重载的 source package；`qwenpaw_notify` 保留为 channel package，内置 mock 单独统计。
- 以失败可见为原则完成清单归一、AxonHub 指标读取、成对 token 测量和 Agent-MCP 绑定验收。

**Non-Goals:**

- 不修改 QwenPaw 上游清单格式，不声称存在 `manifest v2`；不把任意未知 `type` 映射为 WorkFLowWeave `kind`。
- 不迁移凭据、运行数据库、日志、CLI 私有仓库或远端未提交文件；不强制 reset、clean 或覆盖 `myserver`。
- 不把缓存率、token 节省或 Agent 成功从一次服务启动推断出来；没有原始计数就保持未验收。

## Decisions

### 1. 清单兼容采用显式归一层

在配置层增加纯归一函数/模型：读取后先识别 WorkFLowWeave v1 或 QwenPaw-style 形状，再统一生成内部 manifest。QwenPaw 的 `type=collector/channel/tool` 映射到 WorkFLowWeave 的 `kind`；`entry.backend` 仍必须是包内相对 `.py`。`type` 与 `kind` 同时存在且不一致、路径越界、重复 ID 或未知类型均拒绝；manifest ID 是 owner 身份，保留旧版目录名与 ID 不同的兼容行为。依赖和 `qwenpaw_version` 作为诊断/准入元数据，不在没有安装器授权时自动 pip 安装。

替代方案是直接把 QwenPaw JSON 改写成 WorkFLowWeave v1；该方案会丢失上游元数据并把迁移状态隐藏在文件修改中，因此不采用。另一替代方案是宽松接受任意字段并猜测类型，会造成错误插件被加载，违反失败可见原则。

### 2. 十个来源 package 一能力一目录

将现有聚合入口按十个稳定 ID 拆为十个 source package，每个 `register()` 只提交一个 Collector；公共 CLI 适配代码以共享模块引用，不能复制十份业务逻辑。`qwenpaw_notify` 仍可注册其现有 channel 能力，但不计入十个 source inventory；内置 mock 也不计入。发现报告同时给出 package owner 与 capability ID，避免以后把目录数和能力数混用。

替代方案是保留一个聚合包并只统计十个 Collector。它能减少目录数量，却不能满足独立停用/重载和故障隔离验收，因此只作为回滚兼容形态，不作为最终清单。

### 3. 部署拓扑由前端显式指向远端

本地前端的 API base 通过环境/启动配置注入，后端继续在 `myserver` 的既定端口提供 HTTP/SSE。部署检查按 health → plugin inventory → workflow query → trigger → SSE snapshot/terminal → final query 顺序执行；任一边界失败即停止远端推广，不伪造成功。前端不得把远端不可达降级成空本地数据。

### 4. AxonHub 与 token 测量采用成对请求

使用相同模型、系统提示、用户数据、请求参数和时间窗口，分别发送直接 JSON 与紧凑 JSON；记录 AxonHub 返回的原始 token/cached token 字段及请求标识。缓存比率只对明确同一批请求计算，token 节省只对有效成对样本计算。缺失字段、不同模型或数据不一致都输出不可比，而不是补零。

### 5. Agent-MCP 绑定在运行前解析

Workflow 启动前解析绑定 Agent、允许 MCP 和当前版本，生成不可变运行上下文并写入诊断；任何 MCP 缺失/禁用/越权在外部通知前失败。SSE 重连和 resume 只读取该运行上下文，不重新解析全局默认 MCP。这样可以保留 Agent 主动读取 session 的既有语义，同时让绑定关系可审计。

## Risks / Trade-offs

- [远端有未提交改动] → 先记录 `git status` 与文件清单，采用临时同步目录/显式补丁；只修改本 change 指定文件，失败时恢复临时文件，不使用强制覆盖。
- [QwenPaw 依赖未安装] → 只把依赖缺失报告为该包不可用；不在运行时隐式安装，不影响其余九个来源。
- [AxonHub 字段随部署变化] → 通过只读探针保存字段名和原始响应摘要；字段缺失时标记 unavailable，要求后续适配而非猜测。
- [拆包后重复注册] → 在测试中断言十个 capability ID 与 owner 一一对应，并验证错误包不会发布部分声明。
- [前后端版本不一致] → health/manifest 响应带版本和 graph revision；SSE 首帧身份不匹配时停止消费并报告。

## Migration Plan

1. 在本地 worktree 完成本 change 文档与测试，先运行 OpenSpec、静态检查和测试，再把 redesign 分支合并主分支。
2. 合并后重新跑本地后端、前端、HTTP/SSE 和 Windows Tabbit 验收；浏览器证据不足时保持未验收。
3. 仅在本地验收完成后，读取远端状态和备份；把十个 source package、显式清单归一和必要后端代码作为可审阅补丁同步，不触碰远端凭据/数据库/日志或既有未提交文件。
4. 远端以临时分支/独立提交部署，按 health→plugin→workflow→SSE→Agent-MCP→AxonHub 顺序验收；每个大改动独立 commit。
5. 若任一验收失败，停止切换前端 API base，恢复到远端上一个提交或保留旧聚合包作为只读回滚入口；不得删除唯一运行数据。

## Open Questions

无。十个 source package 的计数口径、channel/mock 的排除范围和 QwenPaw 清单的兼容边界均已在本设计与规范中固定。

## Validation

验证命令和证据写入 `tasks.md`；后端测试单次硬超时 60 秒。浏览器验收使用 Windows Tabbit 与 GPT-6 Luna Max，远端指标读取不打印凭据。
