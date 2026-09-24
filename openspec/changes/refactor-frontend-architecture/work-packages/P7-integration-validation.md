# P7 集成与最终验证

根任务：[tasks.md §8](../tasks.md#8-p7--集成清理与整体验收)。依赖 P3/P4/P6 全部完成并提交。依据：[原设计](../../design-frontend-architecture/design.md) §9–§12。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。worker 禁止切 branch、stash、reset 或 commit，只改获分配文件，公共文件请求唯一集成 worker 串行处理。主代理审查并提交本任务 diff，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 钩子。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 所有权与收口

GPT-6 Astra xhigh 集成 worker 在锁定范围内修改 app/router/bootstrap、跨模块 ContinueInAgent、公共配置/规则与最终 E2E；主代理只负责协调、汇总就地 diff、审查和最终提交；P2–P6 期间的路线切换由协调者串行完成并在各包记录，P7 最终审查。pages 用已有 runs 上下文创建 Agent，会缺必要信息才补读；按钮只发意图，agents/runs 互不导入。

核对所有原 URL/query、命名导航、懒加载、404、collector-demo 重定向。删除未引用的两个旧 Demo、旧 View/API/types/composables/domain 出口和零消费者文件，不能留下旧目录中第二实现或永久 compatibility flag。README 说明真实结构、依赖规则、运行/测试入口。

## 验证顺序与证据

按完整单测→typecheck/format/边界→build→Playwright/真实浏览器执行。架构检查覆盖 shared/module/page/app 方向、workflows→resources 唯一例外、跨模块仅 public、model 纯度、SFC 无具体 API/HTTP/EventSource、无 cycles，检查动态/type-only/相对 import。应用普通 HTTP 不留直接 fetch；原始 SSE 协议 E2E 探针与 Playwright route.fetch 明确标注例外。

真实浏览器跑资源→工作流→运行→报告→Agent；固定报告版本、各区失败、Agent 路由输入隔离/停止/分支/文件冲突、375px/44px 触控与长会话输入可见。服务启动不是烟测证据；必须记录实际页面动作和结果。对照 P0 用同构建/数据/路由环境比较入口 chunk、首屏请求和长会话交互，不报告没有测量支持的百分比。

每项失败记录 P0 是否已有及此次影响，不用 broad catch/默认假数据/跳过测试修饰结果。扫描最终 diff 的重复规则、吞错、隐式 fallback、过度 gate、未声明行为变化与本任务提交边界；逐个检查本任务 commit 的路径/diff 排除后端和其他任务文件，不核验整个共享工作区 hash 不变。OpenSpec 文档校验不替代行为验证，其他活动 change 不顺便归档。

## 提交与回退

仅主代理执行正常 commit/post-commit 自动推送，精确纳入本 change 与前端变动，worker 禁止 commit；每次提交都审查暂存路径和 diff，排除并行后端及其他任务。按包记录完整 commit 链和依赖；回退底层时必须处理依赖其 API 的下游提交，不可只还原 shared 保留调用方。本任务不改变后端持久化或并行后端工作，回退单位为可独立验证的前端批次；回退也不得还原其他任务修改。

## 最终结果

待填所有验证命令/退出码、浏览器证据、性能对照、每个本任务 commit 的后端/其他任务路径排除证据、测试时后端 HEAD/dirty 与契约差异、提交链与明确剩余限制。
