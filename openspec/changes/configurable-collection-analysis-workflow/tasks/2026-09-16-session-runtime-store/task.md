# Session 运行时业务存档调整

依据：用户最新明确授权“从最顶级的文档到底下的代码都修改”，session 可读内容与 LangGraph checkpoint 部分分离，由运行时维护；存储幂等，作为可复用 LangGraph 节点，差异通过闭包参数传入。

本任务取代早先仅从 checkpoint 投影 session 的实施方向；contracts 仍是派生说明。模块实现按根 task 的依赖顺序执行，每个模块默认一个 commit。

- [x] proposal 验收9/恢复边界、总设计、Workflow/Collection/Config/Lifecycle/Interaction design 对齐新职责。
- [x] 公共查询模型使用独立 version；SessionReader 对外只读，图内 writer 与之分开。
- [x] Workflow 实现 SessionStore 原子幂等写入、节点闭包复用、SessionView 及 checkpoint 恢复。
- [ ] Collection/API 使用只读业务存档；Lifecycle 注入并关闭两类存储。
- [ ] 验证同键重放、内容冲突、并发分支、存档提交后强退、发送确认窗口、备份关闭/过期，以及真实 HTTP 查询/取消。

实现约束：业务幂等键与 checkpoint ID 解耦；相同提交不增加 version、不回退状态；缺失 checkpoint 不能通过业务存档猜测执行进度；过期保留幂等摘要，不能重放复活正文。默认值继承原模块决策，本次不增加新的保留期限或后台同步器。
