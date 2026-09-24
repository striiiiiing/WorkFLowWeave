# P1 基础边界、API 与 DTO

根任务：[tasks.md §2](../tasks.md#2-p1--基础边界统一-api-与-dto)。用户已审核并授权继续，读取 P0 已通过的单测/type/build 与浏览器环境限制后即可开始。依据：[原设计](../../design-frontend-architecture/design.md) §3.1、§5.2、§8、§10、§12；这是一包串行的公共地基，结束后才开三条业务链。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 输入、所有权与输出

读取 `frontend/src/api/*`、`types/index.ts`、`composables/useQuery.ts`/`useAsyncTask.ts`、`domain/capabilities.ts`/`parameters.ts`、`adapters/schemaValidation.ts`、`main.ts`/`App.vue`/`router/*`、公共 UI/布局/样式及其调用图。独占创建 app、shared、各模块 API/DTO/public，迁移统一传输测试与跨模块类型 import；业务 UI 的深度拆分留给所属包。P1 可为原页面串行迁移调用契约，但不得留新旧两份 DTO 或 fetch 实现。

DTO 归属锁定后要特别拆开 `ResourceMap.workflows`：workflow CRUD 由 workflows API 提供，共用底层 transport。来源 resolve 所消费的 override 输入由资源侧定义，workflows 引用资源公开类型；JSON Schema 需求用 shared/schema 的无业务描述边界，避免 resources/workflows 为读取能力 DTO 反向 import system。

公开 API 均为注入 HttpClient 的工厂。app 创建一个 Axios 实例，模块注入缺失明确报错。P1 选定导出后在下表记录真实符号/路径，不把规划名字当实现已完成。除完整 runs 控制器外，P1 还要实现、测试并冻结供工作流列表调用的最小 trigger/cancel 页面动作控制器；P4 只能在该契约上补齐 sessions 轮询、恢复、报告与详情，不得让 P3 依赖尚未交付的 P4 实现。

| 交接 | 应包含的契约 | 实际导出 |
| --- | --- | --- |
| shared/api | 工厂、薄 HttpClient、ApiError、segment/无业务错误表达 | `shared/api`: `createHttpClient`, `HttpClient`, `HttpRequest`, `ApiError`, `NetworkError`, `RequestCancelledError`, `segment`, `isErrorInfo` |
| shared/async | useQuery 的只读状态/读取时间/refresh；显式 action 结果 | `shared/async/useQuery.ts`: `useQuery`; `useAsyncTask.ts`: `useAsyncTask`, `AsyncTaskResult`, `isTaskSuccess` |
| 模块 API | resources/workflows/runs/agents/system 工厂、DTO、注入 key/hook | `modules/{resources,workflows,runs,agents,system}/public.ts`: `create*Api`, `*Api`, `*ApiKey`, `use*Api`，DTO 在各 `model/types.ts` |
| workflows | 列表控制器与来源使用位置投影，供 P2/P4 直接消费 | `modules/workflows/public.ts`: `useWorkflowList`, `sourceUsage` |
| runs | 已实现并验证的最小 trigger/cancel 页面动作控制器，供 P3 直接消费 | `modules/runs/public.ts`: `useRunActions`, `RunActionResult` |
| system | 能力查询控制器，供 P2/P3 的页面装配消费 | `modules/system/public.ts`: `useCapabilities` |
| resources | SourceUsageView、保存目标与 API 无关 gateway 类型骨架 | `modules/resources/public.ts`: `SourceUsageView`, `SourceSaveTarget`, `SourceConfigEditorGateway`；Schema 编辑输入为 `shared/schema/types.ts` 的 `SchemaCapability` |

## 必验与提交边界

Axios 受控 adapter 验证 URL、0/false/空值参数、JSON 一次序列化、条件请求头、signal、204、无效成功 JSON、非 JSON HTTP 错误/405、仅 health 合法 503、错误信封、网络与取消区分、不自动重试。Async action 的忙碌/失败/void 成功必须可区分；改契约时一次迁移所有调用方并运行针对性用例。Query 覆盖实体改变/同身份刷新失败/A 慢于 B/卸载。

架构检查只维护一套规则，必须解析 TS 与 Vue SFC，覆盖相对、类型和动态 import。P1 可声明逐包到期的旧路径迁移名单，但不能长期豁免新结构。共享规则使用违规 fixture 验证，而不是只 grep alias。P1 编写共享 AST 边界工具并不增加另一套业务验证。app/router/bootstrap 等公共文件由 GPT-6 Astra medium 集成 worker 修改；主代理只协调与汇总交接；集成 worker 审查、验证和提交，普通实施 worker 不提交，所有 worker 不改变 branch。

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

阶段 A 当时尚未浏览器验收，未满足 P1 退出条件，后已提交为 `a2a5510` 并自动推送；当时剩余的 Query/action/公开合同/架构规则由下述阶段 B 完成。根 tasks 由专职集成 worker 按最终证据更新。

过渡出口：`api/{resources,workflows,runs,agents,system}.ts → app/services.ts`（分别随 P2/P3/P4/P5/P6 消费者迁移，P7 清零）；`api/client.ts → shared/api + app/errorMessage`（P7）；`types/index.ts → 各所有者类型`（P7）；`composables/{useQuery,useAsyncTask}.ts → shared/async`、`domain/{parameters,capabilities}.ts/adapters/schemaValidation.ts → shared/schema`、`components/icons/registry.ts → shared/ui/icons`（P7）。旧 SFC 已更新所有引用并直接移动，无转发壳、无双份实现。

Commit：`a2a5510`（已提交并由正常 post-commit 自动推送）；前置规划 `643e1b5`、执行约束 `5786bd1`。


### 阶段 B：查询、动作、公开合同与架构规则（2026-09-25）

根据原设计 §3.1/§5.2/§8/§12.1，沿用同一 Query 和 action 实现，不增加缓存或兼容控制器。`useQuery` 接纳最新响应时记录毫秒时间戳 `readAt`；身份变化清空旧实体/读取时间，同身份刷新失败保留旧值和上次读取时间并暴露错误；scope 释放后中止请求且拒绝刷新。返回的 ref 容器只读（不深度冻结 DTO，编辑器仍自行创建草稿）。首页删除自建读取时间表，直接使用查询的 `readAt`；工作流资源保存后显式刷新目录，避免调用方改写查询拥有的 ref。

`useAsyncTask.run` 唯一结果为 `{status:'success', value:T}`、`{status:'error', error, message}` 或 `{status:'busy'}`，void 成功仍含 success；所有读取返回值的 Agent 调用点已迁移 `isTaskSuccess`。原本在 action callback 内 await 写入并显示成功/导航的调用方保持该控制流，无依赖 undefined 的判断。

runs 将 4xx 明确业务拒绝映射为 `failure`，网络、取消等待或 5xx 映射为 `unknown`，不重试写操作。取消回包 `cancelled:false` 是拒绝而非成功；`cancelled:true` 只表示接受取消请求，不代表后台终态。`triggering` / `cancelling` 相互独立。审查期间发现的嵌套 health 错误不完整问题已修复，HTTP error envelope 与 system health 复用 `isErrorInfo`，不新增另一套 ErrorInfo 校验。

#### 冻结接口与调用例

```ts
// 所有路径均相对 frontend/src；调用发生在页面/组件 scope 内。
import { useWorkflowList, sourceUsage } from '@/modules/workflows/public'
import { useCapabilities } from '@/modules/system/public'
import { useRunActions } from '@/modules/runs/public'
import type { SourceConfigEditorGateway, SourceSaveTarget, SourceUsageView } from '@/modules/resources/public'

const workflows = useWorkflowList() // 或 useWorkflowList({ list }) 注入测试 API
const capabilities = useCapabilities() // 或 useCapabilities({ plugins })
const actions = useRunActions() // 或 useRunActions({ trigger, cancel })
const result = await actions.trigger('saved_workflow_id', abortController.signal)
if (result.status === 'success') {
  // result.value.session_id 是新运行 ID；页面决定导航及刷新。
}
const usages: SourceUsageView[] | undefined = workflows.data.value === undefined
  ? undefined // 未读取成功时保持未知，不表示零引用
  : sourceUsage('source_id', workflows.data.value)
```

- `useQuery<T>(fetcher:(signal:AbortSignal)=>Promise<T>, sources:WatchSource[]=[])` 返回只读 `data/pending/error/readAt` 和 `refresh():Promise<void>`；刷新本身不抛查询错误，错误保留在状态中，不能把 refresh resolve 当作写入成功。
- `useWorkflowList(api:Pick<WorkflowsApi,'list'>=useWorkflowsApi())` 和 `useCapabilities(api:Pick<SystemApi,'plugins'>=useSystemApi())` 直接返回 Query。app/bootstrap 提供唯一 API 实例；缺失模块注入明确抛错。P2 页面消费 workflows/system 并把结果传入资源模块，resources 不反向导入这两个模块。
- `sourceUsage(sourceId:string, workflows:readonly WorkflowDefinition[])` 返回 `{id,name,detached}[]`；只迁移原投影算法，当前草稿替换同 ID 服务端快照由 P3 实现。
- `useRunActions(api:Pick<RunsApi,'trigger'|'cancel'>=useRunsApi())` 返回 `trigger(workflowId:string, signal?:AbortSignal)`、`cancel(sessionId:string)`，以及 `triggering/cancelling/triggerError/cancelError`。结果为 `success(value)` / `failure(error,message)` / `unknown(error,message)` / `busy`。
- trigger 的真实合同依据当前 `src/logagent/interaction/routers.py` 的 `/workflows/{workflow_id}/run`：只运行已保存 Workflow ID，无业务运行选项；第二参数明确是传输 AbortSignal。另一 `/workflows/trigger` 接受 ID 或 snapshot，本包不引入 snapshot/选项第二入口，也不把 AbortSignal 描述为业务选项。P4/P3 基于本已实现合同扩展，不能要求 P3 等 P4 才能运行。
- `SourceSaveTarget = {kind:'shared-resource',resourceId:string} | {kind:'workflow-draft',workflowId:string,sourceId:string}`；`SourceConfigEditorGateway` 的 `resolve(sourceId, override?, signal?):Promise<SourceConfig>` 与 `save(target,value):Promise<void>` 为 API 无关边界，实际编辑器及两种保存流程在 P2 冻结，不在此声明 UI 已实现。
- `SourceUsageView = {id:string,name:string,detached:boolean}`；能力 DTO 的 schema 片段可结构化赋给 `SchemaCapability`（无 system 依赖），完整能力查询和解释仍由 system/page 持有。

#### 架构检查、迁移期限与共用文件

`npm run architecture:check` 运行单一 `scripts/check-architecture.mjs`，再在同一规则上执行 `--fixtures`。TypeScript AST + Vue SFC parser 解析静态/type-only/import-type/dynamic import、re-export、require，检查层级方向、仅 workflows→resources/public、跨模块 public、自模块反向 barrel、model 的 Vue/UI/网络/浏览器状态依赖、SFC transport、普通 fetch、单一 Axios 所有权、未解析依赖和循环。27 个正反例保留相同 source-root 布局及精确预期规则集合，既验证拒绝也验证合法边界，未使用“fixture 模式只发现任意相对 import”替代真实规则。

旧 `api/components/composables/domain/views/types` 消费者按所属 P2–P6 迁移，P7 清零；新 app/shared/modules/pages 不可借旧路径绕过边界。只有 `app/router.ts → views/*` 的懒路由迁移过渡获准。`domain/resources.ts` 的 sourceUsage 只 re-export 唯一 `modules/workflows/model/sourceUsage.ts`，随 P2/P3 消费迁移、最迟 P7 删除。阶段 A 的其他出口及删除包号仍按前段清单执行。

P2/P4/P5 可独立修改各自 modules/pages/所属测试。必须串行交接的公共文件：`package.json`/锁文件、`vite/tsconfig`、`app/*`（尤其 router/bootstrap/services）、`shared/*`、全局样式、`components.d.ts`、`scripts/check-architecture.mjs`/fixtures、共享 tests/helpers 和 Playwright config。只由唯一集成 worker 接收片段并修改，模块作者不要并发改 public 工厂的共同装配。P4 可按主代理安排兼任下一阶段唯一公共文件集成/提交者。

#### 验证记录

- 首轮针对性：`rtk npm test -- --reporter=dot tests/unit/query.test.ts tests/unit/async-task.test.ts tests/unit/api.test.ts tests/unit/http-transport.test.ts tests/unit/runs-api.test.ts tests/unit/runs-actions.test.ts tests/unit/foundation-controllers.test.ts tests/unit/agent-channel-api.test.ts tests/unit/provider-api.test.ts`，9 文件/49 项，退出 0，10.66s。随后移除一项只镜像类型形状的非必要测试，强化卸载后迟到响应的 Query 用例。
- 最终单测：`rtk npm test -- --reporter=dot`，32 文件/160 项，退出 0，77.52s。既有 async-validator 提示为预期测试输出。
- `rtk npm run typecheck` 退出 0；另用 `/tmp/logagent-p1-consumer-tsconfig.json` 继承项目配置，include src 与新增 foundation/runs-actions/http-transport 测试，运行 `rtk proxy npx vue-tsc --noEmit -p /tmp/logagent-p1-consumer-tsconfig.json` 退出 0，确证公开接口消费者类型。
- 全局 format 最初失败；核对四个旧页面相对阶段 A 无 diff，确认是此前遗留格式而非本阶段回归。Collector demo 的正则提示字符串使用等值 `\u003c`，避免 Prettier 将 `<ip>` 误当标签；三个多语句事件处理改为等义箭头函数，避免 Prettier 去分号后导致 Vue parser 失败。其余只有标准格式化，未改变 demo 路由/功能，也未提前执行 P7 删除。
- 最终 `rtk npm run format:check` 退出 0；`rtk npm run architecture:check` 退出 0，117 源码文件和 27 fixture 通过。format 脚本已包含 scripts，防止工具代码漏检。
- 最终 `rtk npm run build` 退出 0，3667 模块，27.29s；入口 `index-KIwTvNcT.js` 291.29 kB / gzip 108.59 kB。对比 A 的 291.32 / 108.56 kB 基本持平；P0 缺同环境稳定浏览器样本，不宣称性能改善。
- 真实浏览器命令：`rtk proxy env LD_LIBRARY_PATH=/tmp/logagent-p0-browser-deps-643e1b5/root/usr/lib/x86_64-linux-gnu npm run test:e2e -- --grep 'workflow create, reload, run, and versioned phase reading|mobile navigation, theme and all primary routes render without overflow' --reporter=line`，退出 0，**2 passed (25.9s)**。使用既有 `serve_backend.py` 的真实 FastAPI/lifecycle/临时数据，预览 13000→后端 14300；浏览器实际经过 Axios/XHR 与同源代理完成工作流创建/回读/运行/版本报告，375px 下首页/工作流/运行/资源/插件路由无横向溢出、主题重载保留，pageerror 均为空。离线采集器在 AI 前结束，无外部模型/邮件/QQ。
- 首次启动将临时库目录误写为缺少 `root/` 的路径，两个用例在浏览器 launch 阶段因 libnspr4 缺失退出 1，未进入产品步骤；更正实际解包路径后全部通过。现有 3000/4300 服务未停止或改写；测试服务由 Playwright 清理。截图为被忽略产物 `frontend/test-results/workflow-editor.png` 和 `mobile-dark.png`。
- 浏览器启动前 HEAD 为 `a2a5510`。并行后端 dirty 快照含 `pyproject.toml`、`uv.lock`，`src/logagent/{agent/service.py,channel/__init__.py,channel/manager.py,config/calls.py,config/store.py,interaction/agent_routers.py,interaction/app.py,interaction/errors.py,interaction/routers.py,lifecycle/service.py,models.py}`，及相应 channel/interaction/config 测试；新增 `agent/channel.py`、`channel/{agent,bindings,conversation,qq,runtime,testing,unified_queue,unified_queue_manager,web}.py`、`interaction/{channel_routers,test_channel_routers}.py` 与相关测试。仅记录该事实，不要求并发状态不变；本包未改、暂存或提交任何后端路径。本次已覆盖 `/api/workflows`、`/{id}/run`、`/api/sessions`、阶段读取及健康/插件/资源真实合同。Agent SSE/commands 的变化仍由 P5 做真实契约核对，本次未把 P0 长会话或完整 Agent 协议写成已验收。
- OpenSpec strict 和指定任务 diff 的空白检查通过；提交前逐项审查前端及本 change 的文件范围。阶段 B 提交标题为 `refactor(frontend): freeze foundation query actions and boundaries`，本记录与实现同一次 commit（提交 hash 由集成交接消息提供，避免文档自引用）；保留正常 post-commit 自动推送，不绕过 hook。

P1 的 2.1–2.6 可退出；P2/P4/P5 可消费上述冻结接口。P1 不包含资源编辑器实体实现、P4 完整运行/首页、P5 协议生命周期、P6 真路由输入隔离或 P7 清理/全流程性能验收；这些仍由原编号承接。P0 1.2/1.3 保持未勾选。
