# Workflow SQL 存储测试

依据[总设计 §1.6](../../design.md#16-定义运行与恢复)的 SQLModel 约束及 [Workflow 持久化设计](./design.md#session-持久化展示与恢复)。测试验证项目自有 SQL 存储统一到 SQLModel 后，原有业务存档与恢复语义保持一致；LangGraph 官方 checkpointer 继续通过官方 API 使用。

## 用例与验收

| 测试文件 | 验收内容 |
| --- | --- |
| `tests/test_session_store.py` | 同键重放复用版本、冲突不发布版本；线程及不同连接并发写入；固定版本读取；关闭与重复关闭；备份禁用和到期清理；真实 trigger 写入失败。新增旧 schema 重放/续写/重开、create 嵌套回滚、内存库跨线程可见，以及外键、业务键、版本约束共 6 项用例。 |
| `tests/test_history.py` | 历史 Collector 通过 SessionView 读取；区分空、缺失、过期、损坏；固定版本及内容预算；损坏内容不泄漏到错误。 |
| `tests/test_workflow_recovery.py` | 父子图 checkpoint、缺失 checkpoint 拒绝恢复、成功分支复用、通知意图与回执、正文备份失败策略、缺失/损坏/过期存档拒绝恢复、取消及中断。 |
| `tests/test_workflow_process_recovery.py` | 子进程真实强退后恢复，验证已保存业务事实不重复执行及通知不重复发送。 |
| `tests/test_workflow_integration.py` | 真实注册、管理器与本地插件协作；资源变化后仍使用原快照；SQLite 文件中业务表与官方 checkpoint 共存。 |
| `tests/test_lifecycle.py`、`tests/test_workflow_lifecycle.py`、`tests/test_workflow_overrides.py` | 启停、取消、活动事务收束、资源关闭与配置覆盖。 |
| `tests/test_interaction.py`、`tests/test_workflow_interval.py`、`tests/test_shared_session_models.py` | API session 查询与控制、定时触发和共享模型契约回归。 |

测试使用临时 SQLite 文件或显式内存库。业务数据查询与故障数据修改使用 SQLModel；checkpoint 内容通过官方 saver API 查询。trigger DDL 用于真实数据库故障注入；旧 schema 测试冻结迁移前 DDL，并通过 SQLModel Session 参数化插入历史数据，避免拿新模型创建的表冒充旧表兼容性证据。两者均为测试夹具，不是第二份生产存储实现。

## 执行方法

在仓库根目录执行，按组设置 60 秒硬超时，避免把进程恢复与全部其他测试塞进同一超时窗口：

```bash
rtk proxy timeout 60s uv run --frozen pytest -q tests/test_session_store.py tests/test_history.py
rtk proxy timeout 60s uv run --frozen pytest -q tests/test_workflow_recovery.py
rtk proxy timeout 60s uv run --frozen pytest -q tests/test_lifecycle.py tests/test_workflow_overrides.py tests/test_workflow_integration.py tests/test_workflow_lifecycle.py
rtk proxy timeout 60s uv run --frozen pytest -q tests/test_workflow_process_recovery.py
rtk proxy timeout 60s uv run --frozen pytest -q tests/test_interaction.py tests/test_workflow_interval.py tests/test_shared_session_models.py
```

单测通过后执行变更文件检查及构建：

```bash
rtk proxy uv run --frozen ruff check src/workflowweave/workflow/session_models.py src/workflowweave/workflow/session_store.py src/workflowweave/workflow/nodes.py tests/test_session_store.py tests/test_history.py tests/test_workflow_recovery.py tests/test_lifecycle.py tests/test_workflow_integration.py tests/test_workflow_process_recovery.py
rtk proxy uv build
```

最小烟测应使用独立临时数据库，在线程中创建 session 并保存正文，关闭后重开，通过 SessionView 固定 version 读取原文，再写终态并推进时间验证正文到期清理。SQLModel URL 构造须能正确处理包含中文、`?`、`#`、`%` 的文件名。

## 已有验证结果与边界

2026-09-19 SQLModel 迁移验收：以上五组分别为 **38、34、37、3、78 项通过，合计 190 项**；Ruff、sdist/wheel 构建及上述存储烟测通过。详细记录见[迁移任务](../../tasks/2026-09-19-sqlmodel/task.md#验证结果)。

这些结果验证的是当前 SQLite 后端及已有 session_headers / session_entries 数据兼容，不代表支持其他 SQL 方言，也不代表已迁移更早的 run_sessions 数据库或重写第三方 checkpointer。测试期间出现 LangGraph/Starlette 弃用提示，未影响通过结果。历史测试记录与后续运行结果应分别记录，不能将文档补充视为重新运行全部测试。
