# SQLModel 存储统一

## 依据与范围

- 用户本次要求：“SQL相关全部采用SQLModel”。这是存储访问层结构调整，项目自有业务表、查询、写入、清理和事务统一使用 SQLModel，不保留 sqlite3 业务实现。
- 依据 [Workflow 设计](../../modules/workflow/design.md#session-持久化展示与恢复) 的独立业务存档、幂等键、事务版本发布与恢复约束，以及[总设计](../../design.md) 的存储职责划分。此次不改变设计职责，不修改 proposal.md 或 design.md。
- LangGraph 官方 SQLite checkpointer 暂保留为第三方存储实现；用户范围问题尚未回复，按现有设计继续使用官方组件，不复制其私有 schema 或自建恢复协议。测试通过官方 API 检查 checkpoint。
- SQLModel 表映射保留现有表名、TEXT 字段、复合主键、唯一键、外键及 JSON/摘要格式，已有业务数据库无需转换；更早的 run_sessions 格式继续显式拒绝。
- SQLite 连接配置和 BEGIN IMMEDIATE 属于驱动层语句，集中在 SQLModel engine/Session 边界。WAL、synchronous=FULL、foreign_keys=ON、secure_delete=ON 沿用迁移前 SessionStore 设置；立即事务保证多个实例分配业务版本和检查幂等键时串行执行。
- StaticPool 保留每个存储实例一条连接，配合现有 RLock 及 check_same_thread=False 支持线程调用，也保持 :memory: 在工作线程间可见。嵌套业务调用复用最外层 Session，只有外层提交或回滚。
- SQLModel 下限使用本次实际安装验证的 0.0.42，上限限制在 0.1 前；具体环境由 uv.lock 锁定。备份故障捕获改为 SQLModel 底层 DBAPIError，不吞掉映射或编程错误。

## 实施与验证

- [x] 新增 session_models.py 唯一定义业务表，迁移 SessionStore 全部业务 SQL。
- [x] 更新 ArchiveRuntime 数据库错误处理、依赖和运行说明。
- [x] 迁移存储及调用层测试，补充原 schema 兼容与嵌套回滚验证。
- [x] 定向单测（每命令硬超时 60 秒）、lint、构建、最小存储烟测。
- [x] 最终 diff 审查：幂等与版本原子性、正文过期、恢复行为、无并行旧存储实现。


## 验证结果

- 存储与历史读取 38 passed（3.40s）；补充 6 项用例验证旧 schema 读取/重放/续写/重开、create 事件失败整体回滚、内存库线程可见、外键/业务键/版本约束。
- Workflow 恢复 34 passed（8.35s）；生命周期、覆盖配置、集成与关闭 37 passed（17.25s）；进程强退恢复 3 passed（29.38s）；API、定时触发与共享模型 78 passed（9.75s）。合计 190 项不同测试，每条命令均受 timeout 60s 限制。
- 旧 schema 测试为独立兼容性基准，通过 SQLModel Session 执行冻结的旧 DDL 和参数化种子插入；故障注入保留 SQLite trigger DDL。这些测试语句不构成业务访问实现。
- 变更文件 Ruff 检查通过；uv build 成功生成 sdist 和 wheel。项目未配置独立类型检查器。
- 独立临时文件烟测通过：带中文及 ?#% 的文件名、线程写入、关闭重开、SessionView 固定版本读取、终态正文过期。
- 已审查变更 diff；生产代码无 sqlite3 导入或手写业务 SELECT/INSERT/UPDATE/DELETE，无第二份表定义或存储实现。第三方弃用提示来自 LangGraph/Starlette，与本次迁移无关。
