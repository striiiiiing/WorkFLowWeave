# 历史 checkpoint 核对修复

## 根因与依据

用户要求继续解决启动时五次“子图 checkpoint 清理失败”。上次
[启动修复](../2026-10-09-backend-startup/task.md)只清理了 resources.json，
留下历史快照问题；本任务接续解决该限制，不修改 proposal.md/design.md。

这是存储读取与归档重放的结构修正。实际 SQLite 数据证明：历史运行已经
使用 MCP/CLI call，但曾序列化六个未使用的来源默认字段，以及
workflow.include_counts。后台归档、执行恢复、MCP 绑定三处直接校验当前
WorkflowSnapshot，未接入已有 migrate_legacy_snapshot。

依据 collection/workflow specs、2026-10-08 contract-cleanup/task.md 中
MCP/CLI 唯一来源及移除业务计数的要求，历史读取允许删除这些无运行语义的
占位字段；不恢复 Collector/Setter 执行链，不放宽新输入校验。
只有已声明 MCP/CLI call 的来源才转换；collector/template 必须 null，
options/setters 必须空对象，on_missing/on_filtered_empty 必须 notice。
这些值来自实际历史快照及先前模型的默认序列化，不新增运行默认值。
非默认旧值及未知字段仍由严格模型明确拒绝。

## 实现决策

- 新增 storage/snapshots.py 的 parse_historical_snapshot，统一调用既有
  历史迁移及 historical_snapshot 校验上下文。后台归档、执行恢复、MCP
  绑定共用该入口；顶层来源和 source_overrides 内嵌来源使用同一转换。
- 原始 checkpoint 和业务快照正文保持不变。转换只在读取副本进行，
  不修改 SQLite 内容、摘要或已提交历史。
- 实际数据库副本进一步暴露旧 phase:collect 存档的 storage_conflict：
  之前移除的 input_format 曾进入不可变归档正文。历史快照带
  include_counts 时，重放继续按原快照生成原 input_format；新快照不生成。
  保留存储摘要冲突检查，不跳过已有条目，也不吞异常。

## 验证

- 新增真实 SQLite checkpoint/业务存储集成测试，覆盖归档核对、重复
  核对幂等、历史 MCP 绑定、恢复材料读取、原始快照不变、MCP call/范围
  与内嵌覆盖不变、新输入严格校验及非默认旧值拒绝：10 passed。
- 提示/提供商/通知历史迁移与业务存储：36 passed。
- checkpoint 清理、父图保留及中断恢复：6 passed。
- 真实 data/workflows.sqlite3 的一致性副本：5 个历史会话全部完成
  reconcile，重复核对不改变业务条目，checkpoint 快照不变，MCP 绑定
  全部可读。没有执行采集、模型或消息发送。
- 使用实际资源文件和上述数据库副本启动真实 CLI（独立端口）：
  /api/health 返回 HTTP 200、ready、accepting_runs=true；启动及关闭
  日志无 Traceback、ERROR 或“清理失败”。
- Ruff、受影响模块 compileall 与 git diff --check 通过。
- 较大的恢复测试整批触及 60 秒硬超时，改跑与本修复相关的恢复测试。
  完成会话恢复、取消续跑、归档中断及启动核对等定向恢复测试：
  6 passed，38 deselected。以上回归共 58 项通过。

用户正在运行的服务进程需重新启动以加载新代码；未停止用户进程。
