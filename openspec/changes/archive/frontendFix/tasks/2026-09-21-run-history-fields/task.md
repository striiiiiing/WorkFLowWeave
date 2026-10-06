# 运行记录名称与按字段筛选

## 需求与依据

- 用户要求运行记录增加工作流名称，并采用按字段搜索的筛选功能。
- 参照 `configurable-collection-analysis-workflow/modules/frontend/design.md` §2 的后端单一事实来源、§3.1 的 SessionRecord 列表及后端过滤/分页约定。新增名称与字段查询是本次用户要求的契约扩展；保留已有 workflow_id、after/before、limit/offset 语义，不改 proposal.md / design.md。
- 根因：SessionRecord、创建事件和列表只持有工作流 ID；RunsView 固定提交完整 workflow_id。简单关联当前工作流配置会在改名或删除后改变历史事实；只过滤前端当前页会漏掉其他页。
- 本次为跨存档投影、HTTP 契约与前端列表的结构性修正，查询语义统一实现于 SessionView。

## 决策

- 工作流触发时将快照中的 name 写入已有不可变 created 事件摘要，SessionRecord 增加 `workflow_name: str | None`；不增加数据库列或改写旧事件。名称随管理摘要保留，正文备份关闭或过期不影响新记录名称。
- 旧记录没有名称摘要时，显式从该运行已有快照正文读取；没有可用历史名称返回 null，前端显示“名称未记录”。空字符串沿用 WorkflowDefinition.name 的现有默认语义，显示“未命名工作流”。不使用当前资源名称替代历史名称。
- API 增加 workflow_name（不区分大小写的包含匹配）、session_id（精确匹配）、status（SessionStatus 枚举精确匹配）。workflow_id 沿用精确匹配，避免改变历史采集器和既有调用的语义；文本框明确要求完整 ID。所有条件在分页前组合执行，名称按普通文本匹配，百分号不作为通配符。
- 前端提供“字段 + 值”的筛选表单，默认字段为工作流名称，依据本次名称可见性诉求；初始值为空、不限制列表。状态选项复用 domain/session.ts，不另设状态字典。
- 切换字段清空待提交值；提交时替换已应用条件并回到第一页；翻页/刷新继续使用已提交条件，不提交正在编辑的草稿。重置清空条件。每页仍为 20 条，依据原 RunsView.PAGE_SIZE，不增加新的分页默认值。
- SessionTable 统一增加名称列并保留单独的工作流 ID 列，监控总览复用；运行详情同步显示名称与 ID。错误继续由 useQuery 明确展示，可主动重试。

## 验证

- [x] 后端 119 项定向测试通过（60 秒硬超时）：创建名称冻结、备份关闭/过期/重开后保留、旧快照和缺失名称、名称/ID/状态过滤、分页顺序、时间/排除条件组合、HTTP 字段校验及返回。
- [x] 前端 12 项定向测试通过：字段请求、名称空值语义、换字段、分页重置、草稿与已提交条件分离、错误重试，以及查询并发和监控总览共享组件回归。
- [x] vue-tsc、受影响文件 Prettier 与 Ruff 检查、生产构建通过。
- [x] Chromium + 真实临时后端 1 条完整流程通过：关闭正文备份、工作流改名/删除后仍展示运行名称，四种字段筛选、状态徽标、重置、详情与 375px 移动端布局，无页面运行异常。
- [x] 对照任务审查差异：状态选项复用现有字典；名称不关联当前资源或改写旧历史；过滤先于分页；失败可见；未改 proposal/design。diff 空白检查通过。

浏览器验证使用临时数据目录，不访问用户的供应商或实际数据。沿用现有 `/tmp/workflowweave-browser-libs/root/usr/lib/x86_64-linux-gnu` 依赖路径。首跑测试定位到 Element Plus 被占位文字覆盖的内部 input，已改为点击可见选择框并通过；截图关闭动画，状态徽标可见性断言通过。截图位于 `frontend/test-results/run-history-fields.png`。
