# Collection任务

状态：实现及主代理 code/spec 审查完成。

依据：[Collection设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：配置注册视图、Workflow SessionView 与公共 SessionReader 协议。

- [x] 保留单来源管理器、Mock/logs 的声明、schema/Setter、真实空状态、有界读取、超时取消与脱敏；不自行发现插件或保存资源。
- [x] 新增 history Collector，注入 SessionReader 读取 SessionView，不导入 WorkflowService、不解析 SQLite/checkpoint 私有结构、不触发原工作流或来源。
- [x] 支持 Workflow/session、最近次数、时间范围及 token 预算；次数按 session 而非checkpoint，固定选中 session version，排除当前 session。参数边界/默认值依据设计和有界读取目标记录于本任务，不伪造精确 token 数。
- [x] 无匹配返回 empty；已选正文未保存/过期返回 missing，损坏 failed；超预算按显式策略截取或拒绝，metadata 说明范围。字段/分组 Setter 明确声明，count 为选中 session 数。
- [x] 通过内置注册入口发布 history；用真实 SessionView 验证展示与历史采集一致、边界及不重跑，再运行既有采集测试（每命令60秒）、lint、构建和历史采集烟测。

## 实现依据与边界（2026-09-17）

- 仅新增 HistoryCollector 及内置导出；既有 Manager/Mock/logs 定向回归通过，沿用只读注册、真实空状态、完整输出校验、有界尾读及取消规则。history 仅依赖 context.session_reader，不导入 Workflow/SQLite/checkpoint 或触发接口。
- options 支持 workflow_id/session_id、limit、after/before、stages、max_tokens、overflow；fields/group_by 由自身 schema 声明。最近次数按 session，选中时固定 version，所有阶段均读该版本；时间按 SessionReader 的 created_at 含边界比较，排除当前 session。指定不存在的 session 视为无匹配；选中后版本消失为 missing，存储损坏 failed。
- 默认 limit=10、上限1000：默认限制历史输入量，上限与 SessionReader 页大小一致。默认 stages=[collect]：只读取原输入，避免把后续包含重复输入的阶段一并拼入；其他阶段显式选择。默认 max_tokens=8192，上限1048576：有界输入预算，按完整序列化输出 UTF-8 字节保守估算，metadata 明示方法，不宣称精确模型 token 数。未选择 tokenizer，因 Collector 不依赖某一 AI 模型。
- 默认 overflow=error，依据设计的显式超限策略；truncate 保留最新的完整 session 前缀，不切断 JSON/Unicode 正文，metadata 记录 included/omitted 的 session/version。一个 session 都容纳不了时明确失败，不能伪装无历史。fields=[] 为 filtered_empty；只选择摘要字段时不要求未选择的正文备份存在。
- 主代理审查了新代码、测试与上述任务细化，未修改 proposal/design。子代理未能接收实现任务，按用户授权由主代理接手。

## 验证

- Collection/配置联合定向 175 passed，3.94秒；追加选中版本消失与取消回归后 history 专项15 passed，2.01秒；各命令60秒硬超时，exit 0。
- Ruff、uv build通过；真实 SessionStore/SessionView 验证内容与展示一致、并发新版本不污染读取、未备份/过期/损坏、最近次数与时间边界、预算与分组、内置注册。

- 全套535 passed，35.42秒，exit 0；独立临时数据库历史采集烟测通过，exit 0。
