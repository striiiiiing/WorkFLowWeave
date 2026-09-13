元信息
- 关联规范：[数据模型](./data-models.md)、[模块接口](./module-interfaces.md)、[总设计](../design.md)
- 任务总数：3
- 预计执行时间：3 小时（人工开发估算；可并发部分不重复计算在关键路径中）
- 执行范围：本轮完成 collection 及其前置依赖需要的公共契约；后续模块沿用这些类型。

# Task 1: 建立 Python 工程与严格数据模型
描述：建立 Python 3.11+ 的 src 布局、依赖和测试入口，落实采集、插件配置、错误以及历史阶段正文需要的交换类型。
输入：数据模型契约的基础约束、SourceConfig、SetterTemplate、CollectorOutput、插件声明和存档结构。
输出：`pyproject.toml`、`src/logagent/models.py`、公共模型测试。
依赖：无。

验收标准：
- 公共模型拒绝未知顶层字段、布尔值充当数值、数字字符串和非有限 JSON 数值。
- ID 不得作为任意文件路径使用，时间必须带时区并规范化为 UTC。
- 采集状态与 count/text/error 保持一致，各实例独立持有可变集合。
- 配置、结果和历史正文可按契约进行 JSON 往返，运行时依赖不进入正文。

# Task 2: 提供可注入协议与统一错误
描述：定义 Collector、只读注册视图、ArchiveReader 和凭据解析协议，让 collection 仅依赖接口；提供可识别且不会回显完整输入的错误。
输入：Task 1 的公共模型及模块接口契约。
输出：`src/logagent/protocols.py`、`src/logagent/errors.py`、CollectionContext。
依赖：Task 1。

验收标准：
- Collector 是异步结构协议，不要求插件继承复杂父类。
- ArchiveReader 仅提供 get/list/load_artifact/availability，不包含触发或写入能力。
- CollectionContext 可以注入只读存档、已固定日志路径和按需凭据解析器。
- 校验和执行错误具有稳定 code；不可控异常的诊断不回显秘密或堆栈。

# Task 3: 统一 JSON Schema 校验边界
描述：提供 JSON Schema 2020-12 声明校验和实例校验，供配置注册及采集校验复用。
输入：Task 1 的 JSON 约束、Task 2 的错误结构和插件字段契约。
输出：`src/logagent/schema.py`、schema 验证测试。
依赖：Task 1、Task 2。

验收标准：
- 无效 schema 和非对象根约束不能发布为能力声明。
- 未声明且被 additionalProperties 禁止的 Setter/options 被拒绝，错误包含可定位字段路径。
- schema 默认值和用户数据被复制，校验不修改调用方对象。
- 校验不采集、发送或发起远程 schema 请求。

## 执行记录（2026-09-13）

- Task 1–3 已完成：工程配置、严格公共模型、注入协议、统一错误和 JSON Schema 校验均已实现。
- 产物：`pyproject.toml`、`src/logagent/models.py`、`src/logagent/protocols.py`、`src/logagent/errors.py`、`src/logagent/schema.py`、`tests/test_contracts.py`。
- schema 在发布声明时解析本地引用，拒绝缺失引用和没有实际类型约束的循环；允许有类型依据的递归，不把 defaults/examples 中的业务数据当作 schema，也不发起远程请求。
- 验证：contracts 76 项；纳入最终全量回归后，Python 3.11.15 和 3.14.3 各 368 项通过。Ruff 检查、格式检查和源码包/安装包构建通过。
- 公共模型包含后续模块交换所需的类型，这不表示 Workflow、AI、Channel 等业务模块已实现。
