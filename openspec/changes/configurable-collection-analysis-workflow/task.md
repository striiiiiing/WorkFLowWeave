# 实施计划（2026-09-16）

旧实现/任务基线：`4dfa8d0072fc16eda4f1c3da25bac36969327deb`。已确认新设计提交：`97ebd68`。

新设计是事实依据，contracts 仅作派生说明。先逐份修正 task.md，再依赖顺序串行实施，每份 task 默认一个代码提交；最多两个子代理，独立审查可并行，代码模块逐个完成。设计调整依据另见 [决策记录](./tasks/2026-09-16-session-design/task.md)。

| 顺序 | 任务 | 依赖与主要差异 | 状态 |
| --- | --- | --- | --- |
| 1 | [公共模型与协议](./contracts/task.md) | 备份、只读 session 协议、全局容量 | 已完成 |
| 2 | [Workflow](./modules/workflow/task.md) | 1及现有注入接口；checkpoint执行进度、幂等存档节点、只读SessionView、恢复与备份 | 已完成 |
| 3 | [配置](./modules/config/task.md) | 1；JSON 原子资源视图、凭据、引用、reload | 已提交 `6adffca` |
| 4 | [AI](./modules/ai/task.md) | 1、3；LangChain Model 异步调用、共享连接多模型、600秒/5重试 | LangChain 迁移完成，最终全套590项通过；详见重写后的模块任务 |
| 5 | [Channel](./modules/channel/task.md) | 1、3；常驻实例、快照绑定、有界关闭 | 修正完成；主代理审查、专项与全套验证通过 |
| 6 | [Mock](./modules/channel/mock/task.md) | 5；可读文本、专用Handler、调用后检查 | 修正完成；主代理审查、专项与全套验证通过 |
| 7 | [Email](./modules/channel/email/task.md) | 3、5；异步SMTP、真实受理回执 | 完成；常驻实例、真实受理语义、本地 SMTP 验证与主代理审查通过 |
| 8 | [Collection](./modules/collection/task.md) | 2、3；history复用SessionView | 已实现并经主代理审查、验证 |
| 9 | [Lifecycle](./modules/lifecycle/task.md) | 1–8；启停、定时、reload、健康 | 待执行 |
| 10 | [Interaction](./modules/interaction/task.md) | 1–9；FastAPI、Typer、完整HTTP链路 | 待执行 |
| 11 | [Frontend](./modules/frontend/task.md) | 10；Vue 3 + Tailwind CSS、无画布流式阶梯编排、设计语言系统、响应式与AAA对比度 | 实现完成，待主代理审查与全套集成验证 |

业务校验、SessionView和API装配以注入接口解除反向依赖，不额外增加资源或运行事实来源。旧SQLite资源仓库及直读CLI按所属任务替换；运行表按新职责收敛为 SessionStore，不再承担独立调度。

每模块按定向测试（后端命令硬超时60秒）→类型/lint→构建→烟测验证，再记录任务结果并commit。基线测试为338项通过；新行为需新增真实边界测试，旧行为与设计冲突时同步修正。

2026-09-16 后续用户已授权从 proposal/design 到代码统一调整：session 业务存档与 checkpointer 分离，由可复用 LangGraph 节点幂等维护，对外只读。新决策见 [任务](./tasks/2026-09-16-session-runtime-store/task.md)，取代先前“只从 checkpoint 投影展示”的实现方向。

本次架构修正优先实施 Workflow：它依赖已完成的公共模型及现有 Collector/AI/Channel 注入接口，无须等待渠道实现替换；后续模块各自完成后再做完整集成验证。

## 2026-09-17 复核与执行分工

- 用户要求默认子代理 `gpt-5.5`、`high`，实现尽量委派，主代理依据 proposal、总 design 和模块 design 审查。本机 Codex `[agents]` 已配置对应默认值，本次新派发也显式指定；保持最多两个子代理和模块顺序实施。
- 已提交不等于完成验收。复核发现 AI 尚存 `model/model_options/models` 多来源及不确定失败重试；Channel 总时限没有覆盖锁/初始化、关闭未协调活动发送；Mock 未落实每条记录的写入完成检查、共享 Handler 重复 start/stop 仍有缺口。先完成这些既定任务，再进入 Email 等下游模块，不修改设计以迁就实现。
- 先前只显示测试进度点、没有拿到退出码和最终汇总的运行，不能作为全套通过证据；后续长命令保留 session_id 并收取最终结果，每个后端测试命令硬超时 60 秒。

2026-09-17 用户要求：实现优先使用 `gpt-5.5/high` 子代理；调用异常时主代理接手。code/spec 审查仅由主代理负责，范围为新增提交及当日尚未审查的改动；每个模块任务验证完成后单独 commit，不混入其他模块半成品。

主代理复核：本轮过程中新增的 `d273cfb`（Channel）与 `7cfa9b9`（Mock）已按相应 design/task 审查；Channel 发现的生命周期问题由 `ad75c7b` 修正。Mock 当前代码含线程归属、完整写入计数及共享 Handler 关闭竞争回归，验证结果见模块 task。

主代理复核：AI 由 `9bbda93` 按 AI design 收敛为单一 `models` 来源并限定 5xx/断连不重试；Channel/Mock 的实例复用、总时限、写入完成检查与共享 Handler 生命周期由 `ad75c7b`、`ebebb13`、`340aae9` 收口；Email 按 Email design 实现常驻 SMTP 实例、按需连接、DATA 肯定接受才成功、其余网络结果为不确定投递，未引入重试或隐式降级。Email 验证为专项 27 passed、全套 519 passed（33.73s，exit 0）、lint/build/本地 SMTP 烟测通过，详见模块 task。


2026-09-17 AI 后续修正：按当前 AI design 及 `3f4ab74` 重写模块 task，对照 `5b90965`/`9bbda93` 删除 Provider.complete、HTTPProvider 和生产 Mock，改为模型工厂注入与 BaseChatModel.ainvoke。HTTP 408/429/5xx 可重试并即时记录诊断，取代上文历史审查中“5xx 不重试”的状态。最终全套590项通过（51.59秒、exit 0），Ruff/build/本地真实HTTP烟测通过；子代理停止后由主代理独立完成。Lifecycle 文件随 AI 装配与日志迁移一并提交；Interaction 及其他设计草稿保留工作区，不据此变更其他模块的独立验收状态。
