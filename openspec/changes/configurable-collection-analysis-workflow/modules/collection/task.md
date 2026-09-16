# Collection任务

状态：待执行，完成后在本文件记录提交前验证结果。

依据：[Collection设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：配置注册视图、Workflow SessionView 与公共 SessionReader 协议。

- [ ] 保留单来源管理器、Mock/logs 的声明、schema/Setter、真实空状态、有界读取、超时取消与脱敏；不自行发现插件或保存资源。
- [ ] 新增 history Collector，注入 SessionReader 读取 SessionView，不导入 WorkflowService、不解析 SQLite/checkpoint 私有结构、不触发原工作流或来源。
- [ ] 支持 Workflow/session、最近次数、时间范围及 token 预算；次数按 session 而非checkpoint，固定选中版本，排除当前 session。参数边界/默认值依据设计和有界读取目标记录于本任务，不伪造精确 token 数。
- [ ] 无匹配返回 empty；已选正文未保存/过期返回 missing，损坏 failed；超预算按显式策略截取或拒绝，metadata 说明范围。字段/分组 Setter 明确声明，count 为选中 session 数。
- [ ] 通过内置注册入口发布 history；用真实 SessionView 验证展示与历史采集一致、边界及不重跑，再运行既有采集测试（每命令60秒）、lint、构建和历史采集烟测。
