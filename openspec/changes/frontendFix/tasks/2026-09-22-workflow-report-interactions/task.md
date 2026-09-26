# 工作流模型目录与报告展开交互

## 需求、根因与范围

- 依据 2026-09-22 用户反馈：并行 AI 分析中的“刷新模型列表”没有使用价值；运行记录过程详情中的“执行完成”等入口难以点中；需要解释数据源与处理模板的区分。
- 模型目录按钮来自 `../2026-09-21-provider-model-flow/task.md`，用于用户在另一标签页维护渠道后手工同步。根因是目录同步依赖额外按钮；目录依然只来自服务端 `AIConfig.models`。
- 报告标题使用原生 summary，但内边距在父 details 上，留白不属于点击目标。依据 `improve-frontend-usability/design.md` 的按需展开过程详情，以及 `configurable-collection-analysis-workflow/modules/frontend/design.md` 的 DEC-LAYOUT-02 / §7.1，标题整行应是至少 44px 高的点击目标。
- 模型同步属于页面生命周期与目录状态同步修正；报告属于局部交互修正。修改 `WorkflowEditView.vue`、`FanOutTaskCard.vue`、`RunDetailView.vue`、`PhaseReport.vue` 与报告折叠样式。数据源/模板只解释现有语义；不改业务模型、proposal.md 或 design.md。

## 决策与不变量

- 删除分析卡片的刷新按钮及其专用 props/events；页面初次加载和重新获得窗口焦点时读取同一 AI 目录。无轮询间隔和第二份缓存；页面离开时移除事件监听。
- 目录查询继续独立于工作流加载，更新目录不能覆盖名称、来源、任务、提示词和汇总草稿。失败仍由现有错误提示与重试按钮显式呈现，不能伪装更新成功。
- 报告复用一个 summary 样式，将内边距纳入原生点击目标，保留浏览器展开箭头、键盘 Enter/Space 和焦点轮廓。44px 下限取自现有前端设计；默认折叠状态与数据读取语义不变。

## 验证

- [x] 定向单测：10 项通过，覆盖返回页面更新分析/汇总目录、保留草稿、失败重试与监听清理，以及工作流模型绑定和报告解析。
- [x] 类型检查、受影响文件格式检查、生产构建通过；`git diff --check` 通过。
- [ ] Chromium：测试代码已覆盖切换渠道配置标签页并返回、选择新模型，以及桌面/375px 窄屏标题右侧留白和键盘展开；本机运行因 Playwright Chromium 缺少 `libnspr4.so` 未能启动，未将其记为通过。
- [x] 对照任务审查 diff：未修改 proposal.md/design.md；未改变后端契约；保留工作区原有 `AGENT.md` 删除及后端修改。
