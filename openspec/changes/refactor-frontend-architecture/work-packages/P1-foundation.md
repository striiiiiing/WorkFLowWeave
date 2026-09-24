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

待填真实导出、命令/退出码、浏览器动作、commit、过渡出口和消费者注意事项。未填不等于通过。
