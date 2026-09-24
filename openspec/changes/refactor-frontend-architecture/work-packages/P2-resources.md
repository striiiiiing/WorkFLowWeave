# P2 资源闭环

根任务：[tasks.md §3](../tasks.md#3-p2--资源闭环)。依赖 P1，可与 P4/P5 并行；交接给 P3。依据：[原设计](../../design-frontend-architecture/design.md) §3.4、§5、§6、§8.2。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。worker 禁止切 branch、stash、reset 或 commit，只改获分配文件，公共文件请求唯一集成 worker 串行处理。主代理审查并提交本任务 diff，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 钩子。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权

写 `modules/resources/**`、`pages/resources/**`、`pages/integrations/useSourceUsage.ts`、资源相关 unit 测试；迁移/删除旧 `views/ResourcesView.vue`、`components/resources/*`、`domain/resources.ts` 中资源部分。P1 已移出的 sourceUsage 不再复制回来。P1 确立的 workflows/system 公共查询/投影只消费，不修改其内部实现；路由/bootstrap/依赖/共享 Schema 变更由 GPT-6 Astra xhigh 集成 worker 按协调者安排串行落盘。

## 公开交接

resources 定义 `SourceUsageView` 和 API 无关编辑输入，pages 将 workflows 来源投影映射后传入。P2 完成同一个 SourceConfigEditor（基础信息/采集参数/处理规则/高级项），冻结只读值与命名动作；保存目标有区分字段的联合类型禁止混用 local/shared/detached 布尔。API 最小 gateway 从页面注入，组件不能自行选择远端保存目标。

资源列表控制器、当前编辑草稿控制器和能力目录各有唯一拥有者。模型列表/凭据保护保留原协议；明文只在当前编辑流程，不能写日志或持久存储。列表刷新不得覆盖打开的草稿；编辑抽屉的 UI 显隐不能产生第二查询。

## 验收与提交

针对性测试涵盖模型/凭据、来源解析、表单/JSON 单值、非法 JSON、失败留草稿、使用位置未知与当前草稿去重、停用绑定和旧模板引用。组件按资源分类、筛选、列表/卡片、供应商、渠道、编辑区拆分，不做视觉重设计。验证顺序为相关单测→type/边界→build→资源页面真实操作及 375px；协调者切换路由后移除对应旧实现并提交。

P3 开工前交接实际组件 props/emits、保存目标联合、gateway 签名及调用样例。首次冻结后如需改签名，先同步 P3，由一方修改资源公开契约。

## 实施证据

待填公开契约、测试结果、浏览器流程、commit 与删除的旧出口。
