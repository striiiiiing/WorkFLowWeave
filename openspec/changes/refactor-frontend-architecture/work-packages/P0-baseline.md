# P0 基线与契约差异

根任务：[tasks.md §1](../tasks.md#1-p0--基线与契约差异)。本文件仅承接基线证据，不另设执行清单。

## 输入与所有权

前端/设计快照为 `4e3c524f799edd079356f8c3975632b7968fccbd`，原 HEAD 为 `cb01cd6`；后端未复制，契约测试使用 `PYTHONPATH=/mnt/d/code/LogAgent/src`。源清单 `/tmp/logagent-frontend-architecture-original-manifest.json` 需要提取永久摘要和相关后端哈希。原工作区只读，`.venv` symlink 与本地数据不提交。P0 只读测试/调查，可由 GPT-5.5 xhigh 承担；不修改业务源码。

依据：[原设计](../../design-frontend-architecture/design.md) §2.1、§11.1、§12.1；前端 package.json 的现有命令和对应 Playwright config 是实际验证入口。测试运行前核对 config 的后端启动路径，不能因 cwd 默认指向旧后端而误验渠道功能。

## 交接要求

P1 需要单测/type/build 基线及 HTTP/Agent 当前契约，完整浏览器/性能基线应在迁移相关闭环前完成。既有失败须有复现命令和错误摘要，区分环境失败与产品失败；与待改传输或真实端点有关且无法解释的失败必须先定位，不用新增 fallback 让基线表面通过。

真实浏览器至少读取首页、一个工作流/报告与 Agent 会话；长会话记录事件规模和相同测试数据入口。性能只做可复现对照，不设无依据提升百分比。测试真实 FastAPI 用临时目录和受控外部依赖，不触发真实邮件/QQ/模型付费调用。

## P0 已收证据（只读）

证据原文暂存于 `/tmp/logagent-frontend-architecture-baseline.md`，以下摘要已复制到 change，避免临时路径成为唯一依据：

| 项 | 证据 |
| --- | --- |
| 安装与单测 | `npm ci` 成功；`npm test -- --reporter=dot` 通过 28 文件/140 项，耗时 86.38s |
| 类型与构建 | `npm run typecheck`、`npm run build` 通过；Vite 转换 3,583 模块 |
| E2E | `npm run test:e2e -- --grep "workflow designer persists independent sources"` 在 Chromium 启动前阻塞，缺 `libnspr4.so`；不能记录为通过 |
| 后端隔离 | 后端解释器解析到 `/mnt/d/code/LogAgent/src/logagent/__init__.py`；E2E 使用 `PYTHONPATH=/mnt/d/code/LogAgent/src`、临时数据；无后端源码修改 |
| 入口 chunk | `index-BpZST3aI.js` 230.63 KB / gzip 85.63 KB；未测首屏请求数与长会话 |
| 其他基线限制 | Tabbit 未执行；375px、Agent SSE/文件冲突和长会话无本轮证据；Node engine/esbuild 安装提示待后续环境复核 |
| 源清单/后端哈希 | 由 `/tmp/logagent-frontend-architecture-original-manifest.json` 与 root hash 复核；待将相关摘要/哈希补入永久记录 |
| 用户 tasks 审核 | 尚未发生；不得推定 |

P0 的 1.2/1.3 尚缺格式检查、真实浏览器、首屏请求数、长会话和永久后端哈希证据，未满足完成条件，保持未勾选。后续执行者补齐并验证客观证据后更新任务；E2E 和 Tabbit 当前缺口继续记录为限制。
