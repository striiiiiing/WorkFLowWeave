# 实施计划（2026-09-16）

旧实现/任务基线：`4dfa8d0072fc16eda4f1c3da25bac36969327deb`。已确认新设计提交：`97ebd68`。

新设计是事实依据，contracts 仅作派生说明。先逐份修正 task.md，再依赖顺序串行实施，每份 task 默认一个代码提交；最多两个子代理，独立审查可并行，代码模块逐个完成。设计调整依据另见 [决策记录](./tasks/2026-09-16-session-design/task.md)。

| 顺序 | 任务 | 依赖与主要差异 | 状态 |
| --- | --- | --- | --- |
| 1 | [公共模型与协议](./contracts/task.md) | 备份、只读 session 协议、全局容量 | 已完成 |
| 2 | [配置](./modules/config/task.md) | 1；JSON 原子资源视图、凭据、引用、reload | 待执行 |
| 3 | [AI](./modules/ai/task.md) | 1–2；600秒/5重试、共享连接多模型、开放扩展参数 | 待执行 |
| 4 | [Channel](./modules/channel/task.md) | 1–2；常驻实例、快照绑定、有界关闭 | 待执行 |
| 5 | [Mock](./modules/channel/mock/task.md) | 4；可读文本、专用Handler、调用后检查 | 待执行 |
| 6 | [Email](./modules/channel/email/task.md) | 2、4；异步SMTP、真实受理回执 | 待执行 |
| 7 | [Workflow](./modules/workflow/task.md) | 1–6；checkpoint执行进度、幂等存档节点、只读SessionView、恢复与备份 | 待执行 |
| 8 | [Collection](./modules/collection/task.md) | 2、7；history复用SessionView | 待执行 |
| 9 | [Lifecycle](./modules/lifecycle/task.md) | 1–8；启停、定时、reload、健康 | 待执行 |
| 10 | [Interaction](./modules/interaction/task.md) | 1–9；FastAPI、Typer、完整HTTP链路 | 待执行 |

业务校验、SessionView和API装配以注入接口解除反向依赖，不额外增加资源或运行事实来源。旧SQLite资源仓库及直读CLI按所属任务替换；运行表按新职责收敛为 SessionStore，不再承担独立调度。

每模块按定向测试（后端命令硬超时60秒）→类型/lint→构建→烟测验证，再记录任务结果并commit。基线测试为338项通过；新行为需新增真实边界测试，旧行为与设计冲突时同步修正。

2026-09-16 后续用户已授权从 proposal/design 到代码统一调整：session 业务存档与 checkpointer 分离，由可复用 LangGraph 节点幂等维护，对外只读。新决策见 [任务](./tasks/2026-09-16-session-runtime-store/task.md)，取代先前“只从 checkpoint 投影展示”的实现方向。
