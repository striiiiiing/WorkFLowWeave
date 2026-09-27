# task1 实施记录（2026-09-20）

依据：`../task.md` 的 task1；既有 `configurable-collection-analysis-workflow/modules/frontend/design.md` §3.2 的工作流字段与系统/插件监控职责。未修改 proposal.md 或 design.md。

- 根因：总览直接渲染 `/api/health` 内部组件；SourceStepCard 和 FanInCard 的高级选项未统一接入编辑页高级模式。
- 范围：DashboardView、AppLayout、SourceStepCard、FanInCard、WorkflowEditView、插件健康投影及针对性测试。仅前端展示修正，不改后端契约。
- 插件按 `(kind, plugin)` 分组，依据 CapabilityDescription 的归属字段（同名不同类型插件可并存）。发现失败项来自 `lifecycle/health.py::plugin_health` 的 discovery_errors，插件标识来自 `config/registry.py::_failure`。无健康报告或存在汇总降级时标为待确认，不把注册成功当作远程连通；现有 API 不进行远程插件探测。
- 总览高级模式位于页面右上角，默认关闭；插件状态始终显示，原内部组件表展开后显示。顶部移除新建工作流快捷按钮，工作流管理原入口保留。
- 全部为空策略、来源输入分隔符、汇聚分隔符、标记不完整结果沿用一个高级开关；默认关闭仅隐藏字段，不重置配置或改变模型默认值。
- 提交隔离：工作区已有其他任务修改；本提交仅包含 task1 差异及高级开关必要接线，保留其他暂存与未暂存内容。

## 验证结果

- 待提交快照在独立目录通过 3 项针对性单元测试、vue-tsc 类型检查、Prettier 检查和生产构建，确认不依赖其他未提交任务。
- 当前工作区通过真实 API 的 Playwright 移动端导航、主题与各主页面无横向溢出冒烟测试（1 项）；浏览器使用现有临时动态库目录。
- diff 复核及空白检查通过。首次单元测试因测试框架 resetMocks 清空 mock 返回值失败，改为在测试内明确配置 API 返回值后复跑通过。
