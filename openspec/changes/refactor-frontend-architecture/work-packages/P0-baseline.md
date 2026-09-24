# P0 基线与契约差异

根任务：[tasks.md §1](../tasks.md#1-p0--基线与契约差异)。本文件仅承接基线证据，不另设执行清单。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。worker 禁止切 branch、stash、reset 或 commit，只改获分配文件，公共文件请求唯一集成 worker 串行处理。主代理审查并提交本任务 diff，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 钩子。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 输入与所有权

历史 P0 在 `/mnt/d/code/LogAgent-frontend-architecture` 的前端/设计快照 `4e3c524f799edd079356f8c3975632b7968fccbd` 上完成，原 HEAD 为 `cb01cd6`；当时后端未复制，契约测试使用 `PYTHONPATH=/mnt/d/code/LogAgent/src`，原工作区只读，`.venv` 为测试 worktree 的本地 symlink。这些是当时事实，不再作为当前就地执行限制。旧清单 `/tmp/logagent-frontend-architecture-original-manifest.json` 仅作历史证据；后续真实测试记录当时后端 HEAD/dirty 和协议状态。P0 只读测试/调查可由 GPT-5.5 xhigh 承担，不修改业务源码或运行数据。

依据：[原设计](../../design-frontend-architecture/design.md) §2.1、§11.1、§12.1；前端 package.json 的现有命令和对应 Playwright config 是实际验证入口。测试运行前核对 config 的后端启动路径、当时 HEAD/dirty 和双向 channel 协议状态；历史通过结果不能证明并行重构后的后端仍兼容。

## 交接要求

P1 需要单测/type/build 基线及 HTTP/Agent 当前契约，完整浏览器/性能基线应在迁移相关闭环前完成。既有失败须有复现命令和错误摘要，区分环境失败与产品失败；与待改传输或真实端点有关且无法解释的失败必须先定位，不用新增 fallback 让基线表面通过。

真实浏览器至少读取首页、一个工作流/报告与 Agent 会话；长会话记录事件规模和相同测试数据入口。性能只做可复现对照，不设无依据提升百分比。测试真实 FastAPI 用临时目录和受控外部依赖，不触发真实邮件/QQ/模型付费调用。

## 历史 P0 已收证据（2026-09-24，旧独立工作区，只读）

证据原文暂存于 `/tmp/logagent-frontend-architecture-baseline.md`，以下摘要已复制到 change，避免临时路径成为唯一依据：

| 项 | 证据 |
| --- | --- |
| 安装与单测 | `npm ci` 成功；`npm test -- --reporter=dot` 通过 28 文件/140 项，耗时 86.38s |
| 类型与构建 | `npm run typecheck`、`npm run build` 通过；Vite 转换 3,583 模块 |
| E2E | `npm run test:e2e -- --grep "workflow designer persists independent sources"` 在 Chromium 启动前阻塞，缺 `libnspr4.so`；不能记录为通过 |
| 后端隔离 | 后端解释器解析到 `/mnt/d/code/LogAgent/src/logagent/__init__.py`；E2E 使用 `PYTHONPATH=/mnt/d/code/LogAgent/src`、临时数据；无后端源码修改 |
| 入口 chunk | `index-BpZST3aI.js` 230.63 KB / gzip 85.63 KB；未测首屏请求数与长会话 |
| 其他基线限制 | Tabbit 未执行；375px、Agent SSE/文件冲突和长会话无本轮证据；Node engine/esbuild 安装提示待后续环境复核 |
| 当时源清单复核 | 旧清单 `/tmp/logagent-frontend-architecture-original-manifest.json` 与 root hash 复核为当时证据；后续不以此要求并行后端或整个共享工作区不变 |
| 当时 tasks 审核状态 | P0 调查时尚未审核；用户随后已明确审核并授权继续，见根任务 1.4 |

P0 的 1.2/1.3 尚缺格式检查、真实浏览器、首屏请求数、长会话及后续真实测试所需的后端版本/dirty 记录，未满足完成条件，保持未勾选。后续执行者补齐客观证据后更新任务；E2E 和 Tabbit 的历史缺口继续保留。用户审核已通过，单测/type/build 基线足以支持 P1 启动，环境阻塞不再作为全体实施的前置门槛；不要求并行后端维持历史 hash。
