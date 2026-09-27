# Lifecycle 模块设计说明补全

状态：已完成文档更新及静态核对。

依据：用户明确要求将本轮 Lifecycle 设计说明写入模块级 `design.md`，授权更新 [Lifecycle 设计](../../modules/lifecycle/design.md)。本次设计文档更新新增任务记录，保留原有 [Lifecycle task](../../modules/lifecycle/task.md) 作为此前重构和验证的历史依据。

- [x] 补充六个实现文件的职责、ApplicationServices 服务容器及四个生命周期入口。
- [x] 按当前实现明确启动装配顺序、Workflow 中断整理和 Interaction lifespan 接线边界。
- [x] 明确资源重载、插件重载冲突恢复、部分发布失败及显式恢复要求。
- [x] 补充本地健康状态与运行准入关系，说明健康查询调整准入的副作用。
- [x] 补充生命周期锁、内部任务复用、调用方取消隔离，以及分步清理超时和重试行为。
- [x] 核对相对链接、文档 diff 和现有实现；本次只修改文档，不重复执行运行时测试。

决策依据：`src/logagent/lifecycle/service.py` 的四个入口、共享锁和清理任务表决定协调边界；`services.py`、`resources.py`、`health.py`、`logging.py`、`formatting.py` 分别提供服务容器、资源接线、本地诊断和日志能力。启动与关闭顺序按照已取得资源及其依赖关系表述，避免将清理概括为机械的构造顺序反转。

默认值依据：30 秒和 10 秒等待窗口沿用原 task 的实现决策及 `service.py` 常量，明确其为分步骤预算，不构成整体关闭时限；本次未新增默认值。

说明澄清：原 task 中“调用方取消保持禁准入”应区分两种取消。调用方取消只结束 shield 外部的等待，内部 reload 仍可成功完成并恢复准入；内部 reload 任务被取消或发布中途失败，才保留必须显式恢复的状态。以本次补全的模块设计说明为准。

## Lifecycle docstring 补充

依据：用户要求以 docstring 形式注释代码，沿用上述模块设计和当前实现；设计不变，因此在本任务中追加记录，不修改 `design.md`。

- [x] 为 `src/logagent/lifecycle/` 七个 Python 文件的模块、类和函数补充中文 docstring，说明职责、资源所有权、准入副作用、取消隔离与清理重试语义。
- [x] 补充资源发布回调的事件循环归属、本地健康探测边界及日志脱敏、字节预算和 handler 所有权约束。
- [x] 将已有的准入锁、UTF-8 轮转计量和日志参数格式化说明移入对应 docstring，未改动执行逻辑或默认值。

验证：以本轮注释前的源码为基线，去除 docstring 后七个文件的 AST 完全一致，且模块、类和函数均有 docstring；Ruff lint、格式检查和限定路径的 `git diff --check` 通过。本轮仅修改注释及任务记录，使用静态检查验证，未重复执行运行时测试。
