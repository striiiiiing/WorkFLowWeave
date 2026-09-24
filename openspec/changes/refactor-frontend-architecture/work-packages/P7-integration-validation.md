# P7 集成与最终验证

根任务：[tasks.md §8](../tasks.md#8-p7--集成清理与整体验收)。依赖 P3/P4/P6 全部完成并提交。依据：[原设计](../../design-frontend-architecture/design.md) §9–§12。

## 所有权与收口

GPT-6 Astra xhigh 集成 worker 在锁定范围内修改 app/router/bootstrap、跨模块 ContinueInAgent、公共配置/规则与最终 E2E；主代理只负责协调、合并、审查和最终提交；P2–P6 期间的路线切换由协调者串行完成并在各包记录，P7 最终审查。pages 用已有 runs 上下文创建 Agent，会缺必要信息才补读；按钮只发意图，agents/runs 互不导入。

核对所有原 URL/query、命名导航、懒加载、404、collector-demo 重定向。删除未引用的两个旧 Demo、旧 View/API/types/composables/domain 出口和零消费者文件，不能留下旧目录中第二实现或永久 compatibility flag。README 说明真实结构、依赖规则、运行/测试入口。

## 验证顺序与证据

按完整单测→typecheck/format/边界→build→Playwright/真实浏览器执行。架构检查覆盖 shared/module/page/app 方向、workflows→resources 唯一例外、跨模块仅 public、model 纯度、SFC 无具体 API/HTTP/EventSource、无 cycles，检查动态/type-only/相对 import。应用普通 HTTP 不留直接 fetch；原始 SSE 协议 E2E 探针与 Playwright route.fetch 明确标注例外。

真实浏览器跑资源→工作流→运行→报告→Agent；固定报告版本、各区失败、Agent 路由输入隔离/停止/分支/文件冲突、375px/44px 触控与长会话输入可见。服务启动不是烟测证据；必须记录实际页面动作和结果。对照 P0 用同构建/数据/路由环境比较入口 chunk、首屏请求和长会话交互，不报告没有测量支持的百分比。

每项失败记录 P0 是否已有及此次影响，不用 broad catch/默认假数据/跳过测试修饰结果。扫描最终 diff 的重复规则、吞错、隐式 fallback、过度 gate、未声明行为变化与后端文件改动；核对原工作区源清单。OpenSpec 文档校验不替代行为验证，其他活动 change 不顺便归档。

## 提交与回退

沿用仓库正常 commit/post-commit 自动推送，精确纳入本 change 与前端变动。按包记录完整 commit 链和依赖；回退底层时必须处理依赖其 API 的下游提交，不可只还原 shared 保留调用方。后端持久化不变，回退单位为可独立验证的前端批次。

## 最终结果

待填所有验证命令/退出码、浏览器证据、性能对照、零后端修改、源 hash 核对、提交链与明确剩余限制。
