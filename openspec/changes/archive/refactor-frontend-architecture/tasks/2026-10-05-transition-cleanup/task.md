# 前端过渡代码清理

开始日期：2026-10-05，验证完成：2026-10-06。用户授权：“清理掉这些过渡代码，该修改的也修改了”。本次在当前 `main` 工作区实施，不修改 proposal/design，不改变既有业务或后端契约。

## 依据与根因

- [原设计](../../../design-frontend-architecture/design.md) §2.2 要求确认引用后删除 Demo，并保留 `/collector-demo` 重定向；§3 要求 app/pages/modules/shared 分层及模块公开入口。
- [原实施任务](../../tasks.md) §8.2 要求清零过渡 re-export、旧实现、DTO 桶、废弃目录和无引用 Demo。本任务记录该清理漏项的完成证据，不将其他历史验收项视为已完成。
- 正式入口 `frontend/index.html → src/app/main.ts` 的源码依赖图已不使用旧目录，但少量单测仍测试旧页面/组件，架构检查仍跳过旧消费者并允许 router 导入旧 views。根因是生产路由迁移后，测试与检查规则未同步收口，属于结构性清理。

## 决策与范围

- 删除旧 `src/views/components/api/composables/domain/adapters/types` 共 45 文件（包括两个 Demo）。测试迁到正式 `AgentPage`、`ContinueInAgent`、AgentHeader 和 `useAgentSession`；不为已删除的组件保留第二套测试入口。
- 删除无源码/测试引用且未从模块导出的 `modules/resources/ui/SourceCollectionFields.vue` 与 `modules/runs/ui/PluginReport.vue`。
- 删除仅访问已不存在 `/agent-demo` 的 `scripts/capture_tabbit.mjs` 和对应 npm 命令，更新前端 README。
- 浏览器回归发现 `frontend.spec.ts` 仍用旧文本框定位模型选择器。依据正式 `AIModelList.vue` 的 combobox 和 Element Plus 选择框容器更新定位方式，保留模型发现错误、加密凭据、保存回读及跨窗口模型目录刷新的原断言；没有修改产品行为。
- 架构检查移除旧消费者、路由、纯模型及循环检查的豁免，显式拒绝退役源码目录与旧路径导入；新增旧页面及 router 导入反例，验证规则确实执行。
- 保留真实旧数据处理：工作流 `retention_days` 的显式转换与其模型/正式编辑器回归、现有后端 DTO 兼容。保留 app 装配单例及 Element Plus 自动生成的顶层 `src/components.d.ts`；它们由正式应用使用，不属于旧目录。
- 不引入默认值、超时或重试策略；使用现有正式模块的行为。无关工作区修改、用户调试数据与其他任务文档保持原样。

## 执行与验证

- [x] 迁移旧路径测试并删除过渡源码、未使用组件和失效脚本。旧目录共 45 个文件、两个无引用模块组件和失效截图脚本已删除；三个单测文件改用正式页面/模块。
- [x] 全量单测、类型检查、架构规则及 fixtures、格式检查、构建。`npm test` 通过 51 个文件/254 项；typecheck、architecture check（171 个正式文件和 29 个 fixture）、本次修改文件格式检查及 build 均通过。全仓 format check 最终仍受既有 16 个源码/测试文件及未跟踪 `frontend/1.json` 的格式告警影响，共 17 个文件；这些无关文件与 HEAD 一致或为用户原有数据，未改动。
- [x] Playwright 真实浏览器回归；确认旧 URL 重定向和正式 Agent 页面。临时真实后端下 `npm run test:e2e` 通过 18 项；覆盖 Agent 正式入口、续接、资源/工作流/运行流程和窄屏布局；`app-router` 单测确认 `/collector-demo` 重定向。
- [x] 复核源码/测试引用与最终 diff，记录结果及实际限制。源码和测试不再引用退役目录；架构检查新增旧页面自身和 router 导入反例。保留工作流旧 `retention_days` 显式转换、后端兼容 DTO 及 collector-demo 重定向；未修改 proposal/design 和无关工作区文件。

补充限制：`openspec validate refactor-frontend-architecture --strict --no-interactive` 返回 Unknown item，因为该 change 已归档，不是当前活动 change。本任务的 Markdown 相对链接、格式及 `git diff --check` 通过；不修改历史未完成任务框来绕过归档验收。本次浏览器后端使用临时数据，Agent UI 使用受控接口，没有调用外部 AI 服务；未将隔离回归作为真实模型连接的验收。
