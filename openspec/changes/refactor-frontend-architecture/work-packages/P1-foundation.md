# P1 基础边界、API 与 DTO

根任务：[tasks.md §2](../tasks.md#2-p1--基础边界统一-api-与-dto)。用户已审核并授权继续，读取 P0 已通过的单测/type/build 与浏览器环境限制后即可开始。依据：[原设计](../../design-frontend-architecture/design.md) §3.1、§5.2、§8、§10、§12；这是一包串行的公共地基，结束后才开三条业务链。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。worker 禁止切 branch、stash、reset 或 commit，只改获分配文件，公共文件请求唯一集成 worker 串行处理。主代理审查并提交本任务 diff，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 钩子。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 输入、所有权与输出

读取 `frontend/src/api/*`、`types/index.ts`、`composables/useQuery.ts`/`useAsyncTask.ts`、`domain/capabilities.ts`/`parameters.ts`、`adapters/schemaValidation.ts`、`main.ts`/`App.vue`/`router/*`、公共 UI/布局/样式及其调用图。独占创建 app、shared、各模块 API/DTO/public，迁移统一传输测试与跨模块类型 import；业务 UI 的深度拆分留给所属包。P1 可为原页面串行迁移调用契约，但不得留新旧两份 DTO 或 fetch 实现。

DTO 归属锁定后要特别拆开 `ResourceMap.workflows`：workflow CRUD 由 workflows API 提供，共用底层 transport。来源 resolve 所消费的 override 输入由资源侧定义，workflows 引用资源公开类型；JSON Schema 需求用 shared/schema 的无业务描述边界，避免 resources/workflows 为读取能力 DTO 反向 import system。

公开 API 均为注入 HttpClient 的工厂。app 创建一个 Axios 实例，模块注入缺失明确报错。P1 选定导出后在下表记录真实符号/路径，不把规划名字当实现已完成。除完整 runs 控制器外，P1 还要实现、测试并冻结供工作流列表调用的最小 trigger/cancel 页面动作控制器；P4 只能在该契约上补齐 sessions 轮询、恢复、报告与详情，不得让 P3 依赖尚未交付的 P4 实现。

| 交接 | 应包含的契约 | 实际导出 |
| --- | --- | --- |
| shared/api | 工厂、薄 HttpClient、ApiError、segment/无业务错误表达 | 待实施 |
| shared/async | useQuery 的只读状态/读取时间/refresh；显式 action 结果 | 待实施 |
| 模块 API | resources/workflows/runs/agents/system 工厂、DTO、注入 key/hook | 待实施 |
| workflows | 列表控制器与来源使用位置投影，供 P2/P4 直接消费 | 待实施 |
| runs | 已实现并验证的最小 trigger/cancel 页面动作控制器，供 P3 直接消费 | 待实施 |
| system | 能力查询控制器，供 P2/P3 的页面装配消费 | 待实施 |
| resources | SourceUsageView、保存目标与 API 无关 gateway 类型骨架 | 待实施 |

## 必验与提交边界

Axios 受控 adapter 验证 URL、0/false/空值参数、JSON 一次序列化、条件请求头、signal、204、无效成功 JSON、非 JSON HTTP 错误/405、仅 health 合法 503、错误信封、网络与取消区分、不自动重试。Async action 的忙碌/失败/void 成功必须可区分；改契约时一次迁移所有调用方并运行针对性用例。Query 覆盖实体改变/同身份刷新失败/A 慢于 B/卸载。

架构检查只维护一套规则，必须解析 TS 与 Vue SFC，覆盖相对、类型和动态 import。P1 可声明逐包到期的旧路径迁移名单，但不能长期豁免新结构。共享规则使用违规 fixture 验证，而不是只 grep alias。P1 编写共享 AST 边界工具并不增加另一套业务验证。app/router/bootstrap 等公共文件由 GPT-6 Astra xhigh 集成 worker 修改；主代理只协调、审查、汇总就地 diff 和提交；worker 不自行提交或改变 branch。

建议先提交可编译的类型/API/基础移动，再提交 Axios/异步语义与测试，每次是可回退单元；最终交接需普通 HTTP 单入口、旧路由可运行且下游接口稳定。记录每条旧出口→新唯一实现→到期包号。后续包不得在共享文件各自修改同一工厂。

## 实施证据

### 阶段 A：类型、HTTP 工厂和入口迁移（2026-09-24）

依据原设计 §3.1/§8.1/§10，将 `app/main.ts`、`app/App.vue`、router/navigation/layout/styles 和 shared 基础 UI/Schema 迁为唯一实现；业务 Views 仍由现有懒加载路由使用。`createHttpClient` 在 app services 建一次 Axios 实例（`/api`、timeout 0、无重试），模块 API 均以 HttpClient 注入。`ApiError` 保留 status/info/path；无响应的网络错误与取消有独立错误类型，204 为 undefined，其余成功 JSON 严格解析。合法 health 503 的结构判断在 system API，传输不包含业务规则。

DTO 已分别归 modules/{resources,workflows,runs,agents,system}/model/types，shared/types 仅 JSON/ErrorInfo；ResourceMap 无 workflows，旧页面工作流 CRUD 及对应测试已改用 workflowsApi。旧 API 是 app/services 唯一实例的 re-export，无第二客户端；业务字段中文映射暂在 app/errorMessage 显式装配，shared/api 无业务词典。

验证命令（cwd `/mnt/d/code/LogAgent/frontend`，均退出 0）：

- `rtk npm test -- --reporter=dot tests/unit/api.test.ts tests/unit/runs-api.test.ts tests/unit/provider-api.test.ts tests/unit/agent-channel-api.test.ts tests/unit/schema-validation.test.ts tests/unit/query.test.ts`：6 文件、35 项通过，10.28s。
- `rtk npm run typecheck`：通过；修复移动 ReportText 的相对引用和两个原模板匿名函数的显式输入类型。
- `rtk npm test -- --reporter=dot`：28 文件、140 项通过，82.16s（原 async-validator 校验提示仍预期输出）。
- `rtk npm run build`：通过，3663 模块；入口 `index-BAKNaJ0k.js` 291.32 kB / gzip 108.56 kB。相对 P0 入口增加约 60.69 kB，包含 Axios 与应用装配，未宣称性能改善。
- 四份 HTTP 测试已改受控 Axios adapter，实际经过 Axios 请求转换，保留 URL/405/文件/命令原契约；更完整取消/序列化/架构用例由阶段 B 补齐。

阶段 A 可供协调者审查提交；尚未浏览器验收，尚未完成 P1 退出条件。根 tasks 不由本 worker 更新。阶段 B 待完成 Query 读取时间/只读状态、显式 action 结果、下游前置控制器/资源 gateway/使用位置投影与 AST 边界检查。

过渡出口：`api/{resources,workflows,runs,agents,system}.ts → app/services.ts`（分别随 P2/P3/P4/P5/P6 消费者迁移，P7 清零）；`api/client.ts → shared/api + app/errorMessage`（P7）；`types/index.ts → 各所有者类型`（P7）；`composables/{useQuery,useAsyncTask}.ts → shared/async`、`domain/{parameters,capabilities}.ts/adapters/schemaValidation.ts → shared/schema`、`components/icons/registry.ts → shared/ui/icons`（P7）。旧 SFC 已更新所有引用并直接移动，无转发壳、无双份实现。

Commit：待协调者审查并填写。
