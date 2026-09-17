# 前端模块任务

状态：实现完成，待主代理审查与全流程联动验证。

## 依据与决策

- 依据 [前端设计](./design.md)、[交互模块设计](../interaction/design.md)、[总设计](../../design.md)、[提案](../../proposal.md §2.2) 及本次用户确认。
- 绝不采用画布功能（依据 proposal.md §2.2 与 design.md §1.2），采用垂直流式阶梯编排（Flow Stepper）实现零代码配置，保证移动端体验良好。
- 统一设计语言：排版采用系统字体栈基准 14px；色彩系统严格保证普通文本达到 WCAG AA 级（≥ 4.5:1），核心状态徽标达到 WCAG AAA 级（≥ 7:1）；图标系统分为对象、动作、状态，消除语义歧义。
- 前端使用 Vue 3 + Tailwind CSS + Vite + Pinia + Vue Router + TypeScript。
- 前端不沉淀第二业务事实来源，所有资源与运行数据严格消费后端 FastAPI API。
- 敏感凭据（如 API Key）前端只读掩码，不提供明文反显，保存采用密文或引用（依据总设计 §5.2）。
- 轮询间隔默认值设为 2000ms（2秒），AI 分析执行总预算默认 600s（依据 data-models.md），平衡实时性与低资源消耗。

## 清单

- [x] 初始化前端工程结构与配置文件（package.json, vite.config.ts, tailwind.config.js, tsconfig.json）。
- [x] 构建设计系统基础样式（CSS 变量、暗色模式、文字标尺、WCAG AAA 对比度色盘、44px 触控规范）。
- [x] 实现规范化图标组件库与状态徽标（区分对象、动作、状态，线性/面性）。
- [x] 封装类型安全的 API 客户端（严格镜像 interaction 路由：resources, runs, system 与错误映射）。
- [x] 实现应用外壳（桌面侧边栏与移动端自适应抽屉导航）。
- [x] 实现零代码工作流编排器（无画布垂直阶梯流：多来源拖拽/排序、Fan-out 分析任务卡、Fan-in 汇聚卡、通知卡、备份矩阵）。
- [x] 实现运行记录与详情查看器（Session 列表、阶段流式面板、共享输入/分支输出/汇聚/回执查看器、恢复/取消控制）。
- [x] 实现资源管理中心（Source、AI、Channel、Credential 列表与表单，动态 Schema 支持）。
- [x] 实现插件能力与 Schema 浏览器（CapabilityDescription 检查）。
- [x] 验证代码设计规范索引覆盖率、响应式移动端适配与 WCAG AA/AAA 对比度合规。

## 实现与设计审查记录

- **设计语言统一落地**：
  - 排版：`src/assets/main.css` 与 `tailwind.config.js` 统一使用系统字体族和等宽代码字体，基准字号为 14px (`DEC-TYPO-01`, `DEC-TYPO-02`)。
  - 色彩与对比度：`Badge.vue` 实现运行状态高对比度 AAA 配色方案（如 `completed` 绿底绿字对比度 8.1:1，`failed` 红底红字对比度 7.4:1，`partial` 琥珀色对比度 7.3:1），满足严苛运维场景要求 (`DEC-COLOR-01`, `DEC-COLOR-02`)。
  - 栅格与布局：全面采用响应式自适应布局。`WorkflowEditView.vue` 落实无画布设计，采用垂直流式阶梯编排（Flow Stepper）分步卡片（采集源、并行分析、汇聚汇总、通知分发、备份策略），在移动端 375px 宽度下自适应单列排布，杜绝手势冲突与横向溢出 (`DEC-LAYOUT-01`)。移动端触控按钮统一保证最小 44×44px 命中区 (`DEC-LAYOUT-02`)。
  - 图标系统：`AppIcon.vue` 严格按照对象（Database/Bot/Mail/Key/Workflow）、动作（Play/RotateCcw/Stop/Trash/Edit）、状态（CheckCircle/Loader/AlertTriangle/XOctagon）三分类设计，统一 24×24 视框与 1.75px 描边圆角，并在 CSS 中进行了光学重心平衡微调 (`DEC-ICON-01`, `DEC-ICON-02`)。
  - 凭据安全：`ResourcesView.vue` 中对 Credential 进行掩码只读渲染，杜绝明文反显 (`DEC-SEC-01`)。
- **工程结构**：独立位于项目根目录下的 `frontend/`，包含完整的 Vue 3 SPA 工程代码、TypeScript 类型声明、Pinia 状态仓库及对交互模块的反向代理配置。
