# 前端重构任务

状态：前端重构已实施；用户反馈的空 HTTP 500 已定位并修复，当前本机链路验证通过。后端仍报告可选 mock 插件重复注册导致的 degraded，未将其记作完全健康。以下清单以实际验证为准，替换旧任务中未经验证的完成声明。

## 依据与边界

- 用户 2026-09-18 明确要求：以当前 `main` 为基线，保留现有外观，采用 Vue 3 / Element Plus，消除明显冗余并整理架构。
- 依据 [前端设计](./design.md)、[总设计](../../design.md)、[提案](../../proposal.md)：保留侧栏、移动抽屉、明暗主题与无画布的纵向卡片编排。
- 接口事实来源为 `src/workflowweave/models.py`、`src/workflowweave/interaction/routers.py`、`schemas.py`、`errors.py`。旧前端设计中的接口示例与当前实现存在偏差，以可运行后端为准；本次未修改 proposal.md 或任何 design.md。
- 用户明确指定 Element Plus，优先于旧任务中的“自主实现原子组件”。不保留 Ant Design 或并行的静态预览实现。
- 重构前前端源码及预览已归档至工作区外 `/tmp/workflowweave-frontend-before-refactor.tar.gz`。不修改用户的后端、IDE 配置或提交分支。

## 根因与结构取舍

局部替换图标条件链只能处理表象。原实现重复维护导航、主题、状态颜色、资源副本和加载状态，且错误处理用空列表/健康状态掩盖接口失败。因此采用结构修复：

- `components/icons/registry.ts` 是唯一图标映射，`AppIcon.vue` 用动态组件渲染，图标名由 TypeScript 约束；仅导入实际使用的图标。
- `router/navigation.ts` 是导航定义，桌面与抽屉共用 `AppNavigation`。主题由外壳单点管理，删除 MutationObserver 与重复主题状态。
- `api/` 仅负责传输与 DTO，页面通过 `useQuery` 持有服务端数据，编辑器只持有一份草稿。删除四个仅复制服务端数据的 Pinia store，并移除 Pinia 依赖。
- `useQuery` 取消过期请求、忽略迟到结果并在作用域销毁时清理；`useAsyncTask` 管理提交状态且显式暴露错误。错误不是空数据或成功结果。
- `domain/session.ts` 统一状态、阶段、产物可用性文案；总览和记录页共用 `SessionTable`。工作流步骤复用 `AIModelSelect`，备份与资源策略采用元数据循环。
- 删除 Button/Input/Modal/Switch 等仅转发参数的包装，直接使用 Element Plus。保留有布局或行为职责的页面标题、卡片、状态徽标和 JSON 字段组件。
- Element Plus 组件与样式按需引入；生产主入口 JavaScript 约 220KB（gzip 83KB），替代全量注册时约 1.06MB 的入口，无大包警告。
- 路由懒加载；新增与编辑路由独立挂载草稿，避免参数切换复用旧表单。

## 契约与默认值决策

- 资源路径 `/api/{kind}`，运行路径 `/api/sessions`。工作流使用 `analyses`、`fan_in`、`backup`，不发送后端没有定义的 description、analysis_tasks、backup_policy。
- 支持后端已有 sources/setters/ai/channels 的创建、编辑、删除。无独立 credentials 接口，因此凭据作为 AI 配置的环境变量引用处理，保留既有加密值但不反显。
- 表单初始值逐项依据 `models.py`：采集 60 秒、渠道 30 秒、AI 600 秒/5 次重试、并发 4、备份默认启用、保留期 null 表示不设过期天数。可选汇聚由 null 表示，启用后默认 `{input}` 提示词及双换行分隔。
- 定时运行默认 null（手动触发），与后端一致。当前内置 API 格式为 `openai_compatible_api`，依据 `lifecycle/service.py` 的工厂注册；旧 `http` 仅作兼容别名。
- 轮询默认 2000ms，沿用原前端任务在实时性与请求负载间的取舍；从请求完成时开始计时，避免重叠。所有终态（含 interrupted）与请求失败均停止，用户可刷新重试。
- 产物请求携带当前选定版本；弹窗展示响应版本，不随后台轮询更新版本标签，不缓存 pending 或过期正文。取消操作读取 `cancelled` 响应并重新查询状态。
- `/health` 的 HTTP 503 仍可携带真实 HealthReport；仅该接口接受此状态。总览不虚构运行容量、在线时长或健康状态。
- Vite 默认代理端口 4300 依据 `SystemConfig.port`，可以用 `API_TARGET` 覆盖。
- JSON 编辑只验证 JSON 对象语法；资源、模型与插件业务限制由后端唯一验证。字段错误必须使父表单校验失败，避免提交此前的有效值。

## 实施清单

- [x] Vue 3 + Element Plus 替换，保留蓝灰布局、卡片、明暗主题。
- [x] 图标、导航、状态映射收敛，删除旧 store、冗余包装与静态预览。
- [x] 后端资源、会话、阶段、健康及错误 DTO 对齐。
- [x] 工作流真实保存与编辑，保留已存在的 source/channel overrides。
- [x] 资源 CRUD、插件与 Schema 浏览、运行列表与详情。
- [x] 请求竞态、销毁清理、串行轮询、JSON 表单校验的自动化测试。
- [x] 类型检查与生产构建。
- [x] 真实 FastAPI 浏览器测试：资源编辑、工作流保存/运行/读取产物。
- [x] 375px 移动端、导航、暗色主题与页面无横向溢出的浏览器检查。
- [x] 最终 diff 审查与格式检查。

## 明确未声称完成的事项

- 本次保留布局和视觉语言，不声称与旧 Ant Design 版本像素级一致。
- 插件复杂参数使用 JSON 对象字段及独立 Schema 浏览；不是完整 JSON Schema 自动生成表单。
- 未进行全站 WCAG AA/AAA 对比度与辅助技术认证；旧任务中的此类断言不再作为验收证据。
- 仓库原先已跟踪 node_modules；新增忽略规则只阻止新依赖文件进入 Git，没有擅自批量更改已有索引。

## 验证记录（2026-09-18）

- 单元测试共 12 项通过：HTTP 路径、错误映射、503 健康报告、204 删除、取消响应、明确版本读取、请求竞态、作用域清理、终态/错误轮询与 JSON 表单。
- `npm run typecheck` / `npm run build` 通过；Element Plus 生成的组件类型声明纳入检查。`npm run format:check` 通过。
- Playwright + Chromium 连接临时目录内的真实 FastAPI，验证资源无效 JSON 拦截与创建/编辑、工作流创建/重新加载/保存/触发/版本化正文读取、375px 导航/主题持久化及各主页面无横向溢出。离线采集器以 empty 模式在分析前结束，不调用外部模型。
- 表单使用 `novalidate` 将交互校验交给 Element Plus，避免浏览器原生 number step 与小数最小值冲突而阻断合法提交；业务校验仍在后端。
- Vitest 对 Element Plus 使用 Vite 内联转换，解决外部模块加载时 async-validator 的默认导出差异；同时保留真实浏览器验证。
- 测试环境缺少 Chromium 动态库，下载并解包到 `/tmp/workflowweave-browser-libs`，通过 `LD_LIBRARY_PATH` 运行测试；未修改系统安装。常规环境可按 README 安装 Playwright 依赖。
- 重构范围的 `git diff --check` 通过；仓库全量检查存在用户原有 `.idea/pyLspTools.xml` CRLF 空白差异，未修改。
- 复查源码：无 Ant Design 引用、图标条件链、重复状态 switch、旧 store 或业务数据失败转空列表的逻辑。保留按不同表单内容展示所需的条件分支。

## 实际环境 HTTP 500 问题（用户反馈后续任务）

用户在实际页面遇到“服务返回了无效 JSON（HTTP 500）”。此前 3 个浏览器测试使用临时 FastAPI 与显式代理地址，只能证明隔离环境中的链路成立，不能作为用户当前启动环境的验收结论；此前完成表述范围过大。

- [x] 先记录实际失败与原有验收证据的边界。
- [x] 检查当前前端进程、代理目标、后端监听端口与启动配置。
- [x] 获取失败请求的真实 HTTP 状态、Content-Type、响应正文，区分代理失败与后端业务异常。
- [x] 修复根因；错误呈现保留 HTTP/代理错误信息，不能把所有非 JSON 错误响应都归为 JSON 解析失败。
- [x] 针对实际失败增加回归验证，并验证用户当前运行链路。
- [x] 更新运行说明和验收结论，明确隔离测试与实际环境的分别结果。

约束：沿用现有 proposal/design，不修改用户后端实现；需要改动范围由真实响应与启动配置证据决定，不添加伪造成功或静默回退。

实际证据：用户 Vite 监听 `127.0.0.1:3000`，没有 `API_TARGET` 环境变量及 `.env` 覆盖，使用配置中的 4300。`GET http://127.0.0.1:3000/api/health` 返回 HTTP 500、`Content-Type: text/plain`、空正文；直连 4300/8000 都是连接拒绝，系统没有后端监听。仓库此前既无 `config.json` 也无 `data/`。这是代理没有可连接的后端，再被客户端优先 JSON.parse 误报；不是后端业务返回了坏 JSON。无法读取用户终端历史日志，不以猜测日志作为证据。

修复决策：保留现有 Vite 进程，使用已有 CLI 的 `config-example` 和 `start` 生成本地配置并启动真实持久化后端；默认 4300 不变，不增加端口探测或自动回退。README 写出两个终端的完整命令，不再引用根目录不存在的启动说明；`config.json` 和 `data/` 忽略进 Git，防止本地运行配置及密钥入库。客户端统一保留非 JSON HTTP 失败的状态和响应元数据，只有成功响应解析失败才报无效 JSON；健康接口的 503 错误信封仍应抛错。

后续验证（2026-09-18，本次实际环境）：

- 通过 `.venv/bin/workflowweave config-example --output config.json` 创建本地配置，`.venv/bin/workflowweave start --config config.json` 启动真实后端，使用项目 `data/` 持久化。保留运行供用户继续操作；不是临时测试 API，也未触发工作流或模型请求。
- 经当前 Vite 的 `http://127.0.0.1:3000/api/health` 与 `/api/sources` 均返回 HTTP 200 `application/json`。健康报告 `accepting_runs=true`，整体 `degraded` 原因为可选 `plugins/mock` 与内置 mock 的 `registration_conflict`；各必需组件 available。未修改后端及插件实现来掩盖这个独立诊断。
- 发现 WSL 挂载目录热更新遗漏，`/src/api/client.ts` 仍返回旧模块。触碰 Vite 配置触发其正常重载后，再次读取确认已提供新错误处理实现，无需终止用户进程。
- `npm test`：19 项通过，其中 HTTP 契约 13 项，新增空 500、HTML 502、空 503、健康错误信封、成功但无效 JSON、异常错误体格式回归。`npm run typecheck`、`npm run format:check`、`npm run build` 通过；新增文件也通过 Prettier，改动范围 diff 空白检查通过。
- 新增 `npm run test:live`，配置明确不启动任何服务器，默认直连当前 3000（环境变量 `WORKFLOWWEAVE_FRONTEND_URL` 可覆盖）。Playwright Chromium 实测 1 项通过：总览实际接收健康数据，七类列表返回 JSON 数组，页面创建唯一 ID 采集源，后端读回确认并删除。无浏览器 pageerror；测试未触发工作流。
- 此前 `npm run test:e2e` 的 3 项仍是隔离环境的历史结果；本轮新证据为上述实际链路检查，不将二者混同。实际环境测试需先按 README 启动前后端，后端停止时应直接失败，不自动补起测试服务。
