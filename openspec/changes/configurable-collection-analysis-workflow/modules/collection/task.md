元信息
- 关联规范：[模块设计](./design.md)、[数据模型 §2.2/4.2/6](../../contracts/data-models.md)、[接口契约 §3](../../contracts/module-interfaces.md#3-数据采集)
- 任务总数：6
- 预计执行时间：6.5 小时（人工开发工作量；Mock、logs、history 可并发）
- 执行范围：本轮首个完整业务模块；配置和存档只先完成本模块实际依赖的部分。

# Task 1: 实现能力描述与来源配置校验
描述：实现只消费注入注册视图的 CollectorManager.describe/validate，验证 options、展开后的 Setter 和模板归属。
输入：SourceConfig、SetterTemplate、配置模块发布的 CollectorRegister、公共 schema 校验器。
输出：`src/logagent/collection/manager.py` 的描述与校验入口、对应验证测试。
依赖：contracts 公共模型/协议/schema；config 只读注册视图及 Setter 展开。

验收标准：
- Manager 不扫描目录、不导入入口、不注册或覆盖能力，describe 返回独立描述对象。
- 未注册 Collector、无效 options 和未声明 Setter 在提交校验时得到稳定错误。
- 模板 collector 不匹配被拒绝，实例显式空列表覆盖模板，同名复杂值不深度合并。
- validate 不执行 collect，不访问日志或历史内容。

# Task 2: 实现单来源异步执行与事实状态
描述：调用已注册 collect 协程，限制整体时间、复制输入、严格验证返回值并关联 source_id。
输入：已保存的 SourceConfig 快照、CollectionContext、Collector 输出。
输出：CollectorManager.collect 和状态/取消/隔离测试。
依赖：Task 1。

验收标准：
- 运行时能力缺失返回 missing 并保留发现诊断，不先以配置校验阻止进入缺失处理。
- 异常或非法状态、count、text、JSON 返回 failed；超时返回 timeout，均不返回未完成正文。
- 外部取消继续向调用者传播，插件 finally 被执行，不新增 cancelled 采集状态。
- 插件不能通过修改收到的 options/setters 或复用输出对象改变调用方配置和既有结果。
- Manager 不执行 on_error/on_missing 等 Workflow stop/skip 策略。

# Task 3: 实现 Mock Collector
描述：提供有界离线记录及 success/empty/failed/timeout 模式；按过滤、排序、投影、分组、格式化顺序处理。
输入：Mock options 和 fields/filter/sort/group Setter。
输出：`src/logagent/collection/mock.py`、公开字段/schema 和 Mock 测试。
依赖：contracts 公共模型/协议/schema；与 Task 1、Task 4、Task 5 可并发。

验收标准：
- 默认配置离线成功，一个 Collector 可由多个独立 SourceConfig 实例使用。
- 原始记录为空返回 empty，过滤或字段投影后无内容返回 filtered_empty。
- count 只表示最终可消费记录数，分组不改变单位，不暴露过滤前计数。
- 模式失败和超时可由测试稳定触发，排序、投影与分组有确定结果。

# Task 4: 实现有界日志尾读 Collector
描述：从注入的日志路径读取 JSONL 尾部，支持等级、模块、session、时间、字段及分组设置。
输入：CollectionContext.log_path，默认 200 行/256 KiB 的 max_lines/max_bytes，以及日志 Setter。
输出：`src/logagent/collection/logs.py`、日志边界测试。
依赖：contracts 公共模型/协议/schema；与 Task 1、Task 3、Task 5 可并发。

验收标准：
- 从文件尾分块读取，单次读取字节不超预算，不为取尾部扫描整文件。
- 未配置或不存在返回 missing；权限、完整行损坏、轮转中断返回可识别失败。
- 文件尾未完成事件被忽略并写入 metadata；预算截断的首行不被误报为完整损坏行。
- count 按处理后的事件计数，原始空与处理后空区分，文件句柄在成功、错误、取消后释放。

# Task 5: 实现只读历史 Collector
描述：选择指定 Workflow 的既有终态 session，读取可信阶段正文，并按 UTF-8 字节估算预算保留完整记录。
输入：ArchiveReader、当前 session、workflow_id、artifact、最近次数、时间范围、token 预算和 overflow 策略。
输出：`src/logagent/collection/history.py`、历史选择和预算测试。
依赖：contracts 公共模型/协议；archive 可信只读 FileArchiveReader；与 Task 1、Task 3、Task 4 可并发。

验收标准：
- 排除当前及非终态 session；时间与次数取交集，创建时间倒序且同时间按 ID 稳定倒序。
- collection 读取 shared_input，analysis 按声明顺序取成功分支，final 只读取已冻结输出；每 session 为一条完整记录。
- 预算包含格式化和来源标记，metadata 明确 utf8_bytes_v1、预算与实际占用。
- truncate 只保留最新完整前缀，首条过大返回 filtered_empty；error 明确报告超限。
- 无匹配为 empty，必要正文未备份/缺失/过期为 missing，损坏为 failed，不跳过缺失伪装完整历史。
- 只调用注入的读取接口，不触发历史 Workflow、原来源或模型。

# Task 6: 集成注册、回归与可运行示例
描述：经配置模块统一注册 mock/logs/history，执行真实临时插件与存档文件的集成测试，给出独立使用 collection 的示例。
输入：Task 1–5、config 插件发现及配置展开、archive 只读实现。
输出：collection 公共导出、`examples/collect.py`、README 使用说明、集成测试和执行记录。
依赖：Task 1、Task 2、Task 3、Task 4、Task 5；config 本轮任务；archive 本轮任务。

验收标准：
- 一个目录插件可注册多个 Collector；冲突或部分声明失败不残留注册且不影响其他插件。
- collection 全部单元/集成测试通过，包含并发隔离、异常、超时、取消及实际文件读取。
- 文档说明依赖安装、执行示例、schema 查询、Setter 模板展开和 history 预算语义。
- 任务记录如实区分本轮已完成部分与未实现的资源写入、Workflow、AI、Channel、API 等后续模块。

## 执行记录（2026-09-13）

- Task 1 已完成：`manager.py` 提供只读 describe 和有效来源 validate；模板归属与覆盖规则在 config.expand_source 中验证，Manager 拒绝尚未展开的模板引用。相关验收联用 config 与 manager 测试。
- Task 2 已完成：实现单来源异步执行、严格输出校验、输入输出隔离、整体超时和取消传播；额外验证插件吞取消、清理异常与私有异常信息不会改变事实状态或泄漏诊断。
- Task 3 已完成：`mock.py` 提供有界离线记录、故障模式及过滤/排序/投影/分组流程。
- Task 4 已完成：`logs.py` 提供有界 JSONL 尾读，覆盖完整行、预算截断、半行、追加、轮转和取消等边界。
- Task 5 已完成：`history.py` 通过 ArchiveReader 选择终态记录、读取可信阶段正文，并按 utf8_bytes_v1 保留最新完整记录前缀。
- Task 6 已完成：三个内置 Collector 经真实注册视图和 Manager 集成；提供公共导出、`examples/collect.py` 与 README。subagent 分别完成 config、logs、archive/history，并对独立分支交叉审查。
- 测试分布：contracts 76、config 48、archive 69、manager 33、mock 17、logs 62、history 58、collection 集成 5，共 368 项。
- 最终验证：`rtk proxy uv run --locked pytest -q` 在 Python 3.14.3 通过 368 项；`rtk proxy uv run --locked --isolated --python 3.11 --group dev pytest -q -p no:cacheprovider` 在 Python 3.11.15 通过同样 368 项；Ruff 与源码包/安装包构建通过。默认示例执行成功，返回 success、count=1。
- 本轮完成 collection 全部任务及 contracts/config/archive 的必要前置；配置持久化、完整 ArchiveStore 写入/维护、Workflow、AI、Channel、API 和最终装配仍按各自计划待执行。
