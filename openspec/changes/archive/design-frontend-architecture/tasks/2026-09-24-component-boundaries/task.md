# Vue 组件与逻辑边界补充设计

## 依据与范围

- 用户在评审中指出 `DashboardPage` 的组件粒度不明确，要求确认 Vue 中的逻辑足够分离，并强调一个组件对应一个 `.vue`。本轮据此补充当前架构草案，不修改其他 change 的设计，不实施前端代码。
- [proposal.md](../../proposal.md) 仍限定为架构设计交付；本次细化 [design.md](../../design.md) §3.2–§3.4，并同步迁移映射、阶段退出条件和验证矩阵。
- 遵循用户 SDD 约定：设计补充另建本任务记录，保留原 [tasks.md](../../tasks.md) 作为首轮交付记录。本次用户反馈仅作为组件与逻辑边界细化的依据，不表示整份草案已全部获批。

## 决策与源码依据

| 决策 | 依据 | 结果与默认值理由 |
| --- | --- | --- |
| 页面入口只装配，模板与脚本同时拆分 | 当前 DashboardView 同时包含四项查询、四张指标卡、运行表和两类诊断 | 明确 Dashboard 组件树与文件归属，避免只抽脚本或整页改名 |
| 一个自有 UI 组件一个同名 SFC | 用户本轮组件粒度要求 | 按语义区块/交互边界拆分；不要求每个标签、组件都额外建立 hook 或测试文件 |
| 页面私有 UI 与模块 UI 区分 | 首页指标跨 workflows/runs/system；报告、诊断、来源编辑各有明确业务所有者 | 首页指标留 pages/dashboard/ui，业务表格/面板归 modules，shared 只收真实跨业务复用 |
| 查询单一拥有者，UI 不直接调用 API | DashboardView 重用 health 数据；useQuery 已负责请求取消与最新响应接纳 | useDashboard 只组合控制器；health 查询一次，读取时间与有效响应一同更新，各区块保留独立失败状态 |
| 保留最近运行数量 | DashboardView 当前调用 runsApi.list({ limit: 5 }) | 继续使用 5，组件拆分不改变首页内容数量 |
| 控制器按生命周期拆分，纯逻辑独立 | Agent 已有 Composer/Transcript/Drawer，但 AgentsView 仍承担命令和状态协调；WorkflowEditView 与 SourceStepCard 共同编辑来源 | 补齐页面最低组件边界，禁止用巨型 usePage/Content 代替分层；工作流仍为唯一草稿 |
| 以职责验收而非固定行数 | 复杂度来自状态、请求和业务范围耦合，行数无法证明分离 | 补充静态依赖规则、组件集成场景和人工职责审查，不新增无依据的行数阈值 |

## 任务

- [x] 核对当前 Dashboard 页面、查询原语、工作流/Agent/资源/运行组件与原设计。
- [x] 细化 Page、页面协调、UI、模块控制器、纯模型和 API 的允许职责。
- [x] 给出 Dashboard 文件树、组件树、查询归属与事件流。
- [x] 补充其他页面的最低组件边界，并同步迁移与验收约束。
- [x] 执行 OpenSpec 严格校验、相对链接与文档空白检查，审查本轮差异。

## 验证记录

2026-09-24 已完成：`openspec validate design-frontend-architecture --strict --no-interactive` 通过；本任务及设计文档无行尾空白；本 change 的相对 Markdown 链接均存在；审查差异确认仅更新设计文档与本补充任务。此次没有业务代码修改，不运行前端/后端测试；这里列出的运行行为是后续实施验收要求。
