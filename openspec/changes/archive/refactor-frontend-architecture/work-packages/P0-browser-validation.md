# P0 浏览器与格式基线补充

调查日期：2026-09-24
工作区：`/mnt/d/code/WorkFLowWeave`
开始 HEAD：`643e1b5a1cf708feb4f06b09aca8a96ba8140067`
分支：`refactor/frontend-architecture`

本文件补充 [P0 基线包](P0-baseline.md) 缺少的浏览器、格式与后端并发状态证据。执行过程中 P1 已开始迁移前端文件，以下严格区分 P0 历史结果、本轮环境 smoke 和并发造成的无效结果。

## 基线来源与并发边界

- `git diff --stat 4e3c524 643e1b5 -- frontend` 为空：开始时 HEAD 的已提交前端与历史基线 commit `4e3c524` 相同。
- 开始时前端源码、包配置和测试文件无改动；后端有其他任务的未提交渠道改动。调查期间 P1 改动了 `frontend/src`、`package.json`、`package-lock.json` 等文件，迁移了 `App.vue`、`main.ts`、`AppLayout.vue`、`AppNavigation.vue` 等。不能把这段并发期间的命令结果当作纯 P0 源码基线。
- P1 在本轮预览期间替换了被忽略的 `frontend/dist`：初读的 HTML 引用旧入口 `index-BpZST3aI.js`，随后预览服务实际返回 `index-BAKNaJ0k.js`。后者与 P0 历史成功构建的入口不同，故本轮页面采样结果只能归为并发 smoke，不可用于 P0 到 P1 的性能对照。
- `frontend/npm ci` 成功，安装 289 个包到被忽略的 `frontend/node_modules`，没有由本调查修改 lockfile。Node `v24.14.0` 低于 `abbrev`、`nopt` 声明的 `24.15.0` 下限；npm 也提示 esbuild install script 尚未批准。P0 历史构建曾成功，当前不据此判断构建失败。

## 格式与构建检查

本轮 `npm run format:check` 与 P1 文件迁移同时进行，结果不构成稳定基线：Prettier 对 `CollectorDesignDemoView.vue:2304` 报 `Unexpected closing tag "label"`，并提示 `AgentChatDemoView.vue`、`RunDetailView.vue` 格式不符。无法确认解析错误是 P1 写入期间的中间状态，故不将其归因于 P0 HEAD。

本轮 `npm run build` 同样与 P1 移动文件竞争，失败于 `src/components/layout/AppLayout.vue` 无法解析其导入的 `./AppNavigation.vue`。失败时两个文件正在被 P1 从旧目录迁移。该错误是竞争条件，不是有效的 P0 构建结果。P0 构建应引用历史成功结果：Vite 转换 3,583 模块，入口 `index-BpZST3aI.js` 为 230.63 KB（gzip 85.63 KB）。

## 浏览器环境与调用

- Tabbit 技能已读取。`tabbit-cli diagnose` 返回 `ok: true`，Tabbit Browser 152.0.7977.83 运行中，Playwright Core 1.62.1。
- 对 `http://127.0.0.1:3000/`、`http://localhost:3000/` 及 WSL 网卡上的临时预览 `http://192.168.5.100:13002/` 均实际提交了 Tabbit `nodejs` 程序。浏览器保留了带 WorkFLowWeave 标题的页面，但程序返回的观察上下文转为 `about:blank`，按 group 恢复时出现 `CLAIM_FAILED`；没有获得可审查的 DOM 快照，故不能记为 Tabbit 浏览器验证通过。
- Playwright 自带 Chromium 原缺 `libnspr4.so`、`libnss3.so`、`libnssutil3.so`、`libasound.so.2`。sudo 安装要求交互密码。为验证环境，在 `/tmp/workflowweave-p0-browser-deps-643e1b5` 下载并解包 `libnspr4`、`libnss3`、`libasound2t64` 和 `libasound2-data`，只在命令级 `LD_LIBRARY_PATH` 使用，`ldd` 已无缺失库；没有改系统包。
- 本地 Playwright 随后成功访问预览首页并观察到 UI 文本、无页面异常及无失败请求，但页面加载的是上述并发替换后的 `index-BAKNaJ0k.js`，不能作为 P0 页面验收。该并发 smoke 的首次加载样本发起 4 个 API GET：`/api/workflows`、`/api/sessions`、`/api/plugins`、`/api/health`。数据来自当时已运行的 `127.0.0.1:4300`，健康状态为 `degraded`，可选 mock 插件报告 `registration_conflict`；未执行任何写入。不要将该请求数或健康状态混入 P0/P1 对比。
- 临时 SmokeModel 后端在 `127.0.0.1:14301` 启动并返回 `ready`，但 P1 覆盖构建产物时停止了长会话用例；未发送消息或访问外部模型/邮件/QQ。
- 调查创建的预览和 SmokeModel 服务均已停止。开始时已存在的服务 `127.0.0.1:3000`、`127.0.0.1:4300` 未停止或改写。

## 后端契约快照与未完成项

开始 HEAD 为 `643e1b5a1cf708feb4f06b09aca8a96ba8140067`。当时 `git status --short` 已显示后端渠道任务有多处 tracked 修改及新增文件，包括 `src/workflowweave/channel/*`、`src/workflowweave/interaction/channel_routers.py`、渠道路由测试和相关生命周期改动。P0 不要求这些文件 hash 保持不变，也未编辑它们。正在运行的 4300 服务呈现的是启动时进程状态，不能单凭该服务健康输出断定所有当前 dirty 代码均已加载。

协议核对应以 [渠道任务 §4.2–§4.3](../../redesign-agent-channel-manager/tasks.md) 为依据：HTTP 保留现有响应字段/状态码并返回真实 `turn_id`；后端契约测试使用现有前端请求，核对 `action/session/request_id`、`kind/result`、`TurnAccepted/AgentSession`、原 SSE 信封与游标。另按任务 §5.6 保持目标单测、静态检查、受影响包构建、最小 HTTP/浏览器烟测的顺序；后端单测命令硬超时 60 秒。

仍待稳定基线上补做：

- 在 P1 不再重写基线产物的窗口，核验首页、一个工作流或报告页和 Agent 会话页。
- 对 Agent 长会话记录事件数、DOM/交互数据与固定测试数据入口；只使用 `serve_agent_backend.py` 的确定性 SmokeModel，不连接真实模型或渠道。
- 重新执行格式检查并区分 HEAD 原有问题和 P1 实现问题；本轮并发结果不能作判断。
- 重新执行 P0 来源下的最小真实后端浏览器流程。当前可复用的用户级 Chromium 依赖仅位于 `/tmp`，运行时需设置上述 `LD_LIBRARY_PATH`。
