# 公共模型与协议任务

状态：待执行，完成后在本文件记录提交前验证结果。

依据：[公共模型与协议设计](../design.md)、[总设计](../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：无。默认一个模块提交，只实现各模块共用的数据和窄接口。

- [ ] 补齐 BackupPolicy、session 展示/正文可用性的数据约定；WorkflowDefinition 引用备份策略，SystemConfig 恢复全局运行容量设置。默认启用全阶段备份（proposal 默认保存）；默认容量沿用现有 RunCoordinator 的 4。保留天数如未指定则不自动过期，避免发明既有数据删除期限；显式期限须为正整数。
- [ ] CollectionContext 增加可注入的 SessionReader 只读协议，供历史 Collector 调用；不得导入具体 Workflow/LangGraph 或序列化运行时依赖。为资源仓库、渠道注册视图提供必要协议，业务模块不依赖具体存储。
- [ ] 保持 Pydantic 默认转换与未知字段拒绝，扩展内容严格 JSON-compatible；补齐投递结果的状态/attempts/error 一致性校验。
- [ ] 同步派生 contracts 中受本次设计影响的职责、持久化和生命周期说明，不引入新的设计来源。AI 多模型配置与 600/5 默认值由 AI 模块任务统一实施，避免分拆迁移。
- [ ] 定向模型/协议测试（60 秒硬超时）、lint、构建和序列化烟测；记录通过数量与命令。
