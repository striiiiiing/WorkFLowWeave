# P4 运行、系统与首页

根任务：[tasks.md §5](../tasks.md#5-p4--运行系统与首页闭环)。依赖 P1，独立于 P2/P3/P5/P6。依据：[原设计](../../design-frontend-architecture/design.md) §3.3、§3.4、§4、§5、§9。

## 文件所有权

写 `modules/runs/**`、`modules/system/**`、`pages/runs/**`、`pages/plugins/**`、`pages/dashboard/**` 及相应测试；迁移旧 RunsView/RunDetailView/PluginsView/DashboardView、report UI、SessionTable/StatusBadge、useSession、domain/session/report/pluginHealth/capabilities。P1 的 system 能力查询与 workflows 列表公开契约需保持稳定，P2/P3 在消费它们。

## 交接与职责

runs 提供列表/详情/阶段控制器、触发/取消/恢复操作和已加载只读运行上下文；报告身份固定 `(session_id, version, stage)`。UI 接受报告解析结果，不自行请求，不 import router；恢复资格来自后端。轮询 2000ms 从前次请求结束计时，终态/错误停止。

system 拥有 plugins/health 独立查询、诊断投影与 reload。Dashboard 按指定组件树组合：Page、Metrics/MetricCard、RecentRunsPanel/SessionTable、SystemHealthAlert/PluginHealthPanel/ComponentHealthPanel。useDashboard 只组合 workflows/runs/system 公开控制器；health 一份结果用于三个消费者，运行列表 limit 5，读取时间随接纳响应更新。

## 验收与提交

报告版本改变清旧正文、局部 artifact 失败、分页筛选提交、轮询不重叠、取消/恢复与未知写入结果；首页任意一项失败不遮挡其余结果且不显示错误零值，统一刷新不引入全页单一成功态。系统健康合法 503 与 error 信封分别测试。

建议 runs 和 system/dashboard 分为两个可运行提交；前者交接 P7 已加载上下文与续接按钮意图，后者交接首页所有区块。按每闭环单测→type/边界→build→真实浏览器验证后由协调者切换旧路由；不要在 runs 实现 Agent 请求。

## 实施证据

待填实际公开出口、运行/首页测试与请求计数、浏览器结果、commit 及旧文件删除。
