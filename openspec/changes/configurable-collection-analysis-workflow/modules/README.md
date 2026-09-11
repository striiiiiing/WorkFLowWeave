# 模块目录与实施顺序

本目录将上级 [proposal.md](../proposal.md) 与 [design.md](../design.md) 的七个模块分别落实为独立目录。每个模块维护自己的 `proposal.md`（做什么与验收）、`design.md`（接口与实现设计）和 `tasks.md`（元信息、任务列表、执行顺序）。技术选型（ADR）保持待讨论。

| 顺序 | 模块目录 | 职责 | 前置模块 |
| --- | --- | --- | --- |
| 1 | [configuration](configuration/) | 公共模型、系统配置、资源与快照 | 无 |
| 2 | [archive](archive/) | session 记录、阶段备份与恢复材料 | configuration |
| 3 | [collectors](collectors/) | 插件发现、Setter、Mock/日志/历史采集 | configuration、archive |
| 4 | [ai](ai/) | 可复用模型、系统提示词和工具执行 | configuration |
| 5 | [channels](channels/) | 通知能力、插件生命周期、文件/邮件投递 | configuration |
| 6 | [workflow](workflow/) | 定时触发、编排、并行分析、汇聚、通知及恢复 | 前五个模块 |
| 7 | [interaction](interaction/) | FastAPI、薄 CLI、启动关闭与完整验收 | 前六个模块 |

先补齐各目录的 proposal 和 design 并提交。实施时，先写当前模块的三层 tasks，再交由 subagent 执行；完成该模块的验收测试、审查并提交后进入下一个模块。无依赖的审查和文档整理可以并行，模块集成与验收保持上述顺序。首版完成后再实施后继版本。

根目录的 QwenPaw 解读用于借鉴注册表、Manager、平台适配器和队列的职责划分；项目范围及行为始终以上级 proposal/design 为准。
