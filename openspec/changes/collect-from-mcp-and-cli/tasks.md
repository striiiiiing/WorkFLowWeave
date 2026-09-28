# 任务与决策依据

依据：用户在 2026-09-28 的要求和后续澄清；[proposal](proposal.md)；历史 [采集契约](../archive/configurable-collection-analysis-workflow/specs/collection/spec.md)、[Workflow 契约](../archive/configurable-collection-analysis-workflow/specs/workflow/spec.md)、[Agent 接口契约](../archive/add-file-centric-agent/specs/agent-interface/spec.md)。本变更没有单独的 design.md，实现决策及验证记录于下文。

## 任务

- [x] 1. 记录最初的 MCP/CLI 并列来源、获取/转换拆分、格式与限额、移除业务计数以及 Agent 原始 MCP 接续需求。
- [x] 2. 依据用户要求重新审核全部契约，补齐 [共享 MCP 层](specs/mcp-runtime/spec.md)、[采集](specs/collection/spec.md)、[Workflow 输入处理](specs/workflow/spec.md)、[Agent 接口](specs/agent-interface/spec.md)，同步 [格式说明](formats.md) 与 proposal 的能力列表。
- [x] 3. 对本次文档修订运行 OpenSpec 严格校验，复核跨文件约束和相对链接，记录验证结果。
- [x] 4. 根据本契约完成实现设计：定义共享 MCP 服务配置及 transport 支持范围、快照和凭据引用、工具目录版本与缓存失效、连接会话隔离、原始结果及处理视图模型；确认 CLI 执行/退出/取消行为、格式支持矩阵、token 计量和确定性截取算法。
- [x] 5. 实现共享 MCP 层：服务与工具身份、目录加载/缓存/刷新、schema 查询、范围与参数校验、按需连接、原始结果与执行事实。覆盖冷启动、工具同名、目录变化、断线及结果未知场景。
- [x] 6. 修改采集和资源配置：用 MCP/CLI 调用描述替换来源对 Collector 的依赖，保留原始结果和获取事实，分离 stdout/stderr，移除正计数条件。处理旧来源、Setter、公共调用 API 和旧运行数据的明确迁移或不兼容提示，不用新字段包住旧处理链维持双重来源。
- [x] 7. 实现 Workflow 输入视图：严格 JSON 识别、MCP 重复文本副本处理、格式转换、字段/单项/总限额、错误及截取标识；验证多模型计量、语法有效性、按配置顺序分配预算、非 JSON 原文和原始结果不可变。
- [x] 8. 适配存档与恢复：分别记录获取结果和处理结果，在现有存档策略下复用原始内容；转换失败重试不重新采集，内容缺失或外部调用结果未知时明确报告。
- [x] 9. 改造 Agent MCP 入口：以单个 `mcp` 代理承载状态、目录/搜索、描述和调用，接入共享层；替换 Collector 网关及相关提示、schema 大结果展示、执行调度与事件绑定，避免旧入口和新入口重复暴露同一能力。
- [x] 10. 实现 Workflow → Agent 运行时交接：冻结服务引用及来源关联，按服务去重并保留失败来源；持久化会话绑定，在恢复/分支时保留范围；结果调用绕过 Workflow 处理链，超大结果和非文本内容由 Agent 自身展示机制处理。
- [x] 11. 适配前端和 API：沿用来源配置流程，提供共享 MCP 目录驱动的参数表单、CLI 执行方式和格式/限额说明；Agent 展示实际 MCP 工具身份及调用状态，移除界面对固定 Collector 名称或旧工具数量的假设。
- [x] 12. 完成上述行为的契约/集成测试及最小真实 MCP 调用验证，复核移除的计数、旧 Collector 依赖和重复目录；文档校验不能替代运行验收。

## 模块边界与依据

| 契约 | 拥有的职责 | 依据与原因 |
| --- | --- | --- |
| `mcp-runtime` | MCP 服务配置、目录/schema、认证引用、连接生命周期及原始调用 | 用户确认 Agent 也整体适配 MCP。共享同一套基础能力，避免 Workflow 和 Agent 各维护目录、连接和参数规则；有状态连接不强制跨运行共用。 |
| `collection` | MCP/CLI 调用描述、参数配置视图、获取事实与原始结果 | 用户要求采集成为配置视图，获取与处理拆开；CLI 是并列来源。 |
| `workflow` | 原始结果的输入视图、JSON 处理/格式与输入预算 | 用户要求转换只作用于 JSON，非 JSON 文本保持表示，格式与总预算在 Workflow 级固定。 |
| `agent-interface` | 本次服务绑定、按需工具发现、模型 schema 暴露、原始结果展示 | 用户明确本轮计划包含 Agent 架构适配，不能只在提示里追加 MCP 名单。 |

参考 [pi-mcp-adapter README](https://github.com/nicobailon/pi-mcp-adapter/blob/main/README.md) 的代理模式、Lazy Servers、显式配置快照、Direct Tools 和 Output Guard，以及 [proxy-modes.ts](https://github.com/nicobailon/pi-mcp-adapter/blob/main/proxy-modes.ts) 的搜索/描述/调用处理。核对日期为 2026-09-28；当时包元数据版本为 `3.1.0`，这些链接指向上游可变的 main，不作为依赖锁定。采用其单代理、按需 schema、元数据缓存及按需连接的设计；Python 项目如何使用 MCP SDK由实现设计确定，不以该 TypeScript/Pi 扩展直接可嵌入为前提。

[DeepSeek Harness discussion #4992](https://github.com/deepseek-ai/deepseek-harness/discussions/4992) 介绍的是社区插件，其两个元工具也证明了目录与模型 schema 可分离。这里选择 Pi 的单代理形式；本次不引入 directTools、搜索后自动激活原生工具、脚本 VM、语义搜索或自动审批流程。代理启动或校验失败应明确报错，不复制社区插件的全量工具透传 fallback。按需 schema 仍会占用会话历史，固定的是常驻代理定义，不是整次请求 token 成本。

迁移前的 `src/logagent/agent/builtin/plugin.py` 与 [Collector 网关](../../../src/logagent/agent/gateway.py) 已具有 list/schema/call 外形，但后端绑定 Collector 和来源参数；[Agent 执行入口](../../../src/logagent/agent/graph.py) 对 `plugin` 名称具有调度和 schema 输出特例。此次需改造这些绑定及 [会话资源捕获](../../../src/logagent/agent/service.py)，不能仅更名或传一段服务列表。迁移前的 [结果模型](../../../src/logagent/models.py) 以正计数判成功，[Workflow 汇合](../../../src/logagent/workflow/stages.py) 会拼接计数，都与新契约冲突。

## 默认行为与审查决策

- 格式默认 `none`：用户明确允许不转换，缺省配置不应擅自改变正文表示。Workflow 限额省略/`null` 表示不限额；采集项省略/`null` 继承，只接受正整数覆盖。避免引入未经要求的数值预算，也避免 `0`、缺省、禁用三个含义混用。
- 单代理且不自动激活原生工具：遵循 Pi 的默认代理模式，防止多轮搜索又把全量 schema 累积到注册工具列表。范围内未加载服务必须可发现，缓存缺失不能误报空目录。
- 交接粒度是服务：用户要求给 Agent 原始 MCP 能力，因此同一服务的其他可用工具也可按需发现；原采集参数只是追溯资料，不限制后续问题。失败来源也保留以支持继续排查，CLI 不自动授予 MCP 能力。
- 原始结果与视图区分：MCP 返回可能同时含结构化数据、重复 JSON 文本、说明和图片。保留协议信封，Workflow 只对提取出的业务内容处理；Agent 的原始能力不等于无限内联正文，沿用独立 Agent 展示预算并保留完整读取路径。
- 字段限额采用叶子值粒度，以 JSON 标量表示计量，使口径独立于所选输出格式；避免同一嵌套内容被父容器和子字段重复扣减。字符串可截前缀，数字/布尔/null 不改值。后续整体预算覆盖字段名和结构开销，截取后的结构化片段必须重新序列化，避免破坏 JSON、CSV 引号和 TOON 长度声明。
- 同一共享输入面对多个模型时按各自 token 口径校验；来源标识、分隔符和截取说明计入预算。移除的是业务条数统计，限额所需的 token 计量和格式语法长度仍然必要。
- 获取与处理状态分开后，转换失败不应触发外部重采。复用现有存档策略，只对实际保存的原始内容承诺恢复；旧资源和旧运行迁移是实现设计的必做项，不默认为兼容。

格式库核验：`ison-py`、`zon-format` 均有官方 Python 来源；TOON 官方 Python 仓库提供 beta 转换实现，但 2026-09-28 的 PyPI `toon-format` 元数据仍为占位 `0.1.0`。详见 [格式说明](formats.md)。实施设计需锁定可用版本和支持矩阵，以项目样例验证字段、类型、精度与边界值，不承诺固定 token 节省比例。

## 本次验证

契约修订阶段：`openspec validate collect-from-mcp-and-cli --strict --no-interactive` 通过；本变更 7 个 Markdown 文件的本地相对链接和行尾空白检查通过。跨契约复核覆盖来源/处理状态、JSON 原文与副本去重、分层预算、代理 schema、交接范围以及存档恢复，修正了 `none` 模式下结构化内容与等价原文的优先级，并明确 Agent 参数不隐式继承采集配置。该阶段尚未执行实现与运行测试；实现后的验证见下文。


## 实施记录（2026-09-28，feat/collect-from-mcp-and-cli）

本次为结构性实现：采集契约、资源快照、Workflow 输入与 Agent 工具入口共同切换，禁止新字段包住 Collector/Setter 旧链。此变更无 design.md，依据上列四份 specs 记录实现决策，不修改其他变更的设计。

- 共享 MCP 采用 Python SDK 1.30，支持 stdio / Streamable HTTP / SSE。每次目录加载或调用独立连接，初始化后刷新真实目录再验证/分派；短连接不跨运行共享有状态会话。缓存按完整配置（含凭据引用）的 SHA-256 索引，只保存工具元数据。连接、验证、分派、回执阶段明确，分派后不自动重试。
- 服务资源类型 `mcp_servers`；来源 `call` 是 MCP 或显式 CLI argv/shell 联合类型。MCP 的 env/headers 只接受已有 Credential 引用模型；运行快照持有服务定义，不把配置加入模型提示。CLI 超时/取消终止进程组，stdout 为正文、stderr 为诊断。
- `input_processing` 的 format 默认 none；total_tokens/item_tokens/field_tokens 默认 null。来源 `limits` 只覆盖后两者。默认值直接沿用本任务既有默认决策，不新增隐含数值 token 上限。来源调用超时沿用旧 SourceConfig 的 60 秒。
- 获取结果 `CollectionResult.raw` 与 `InputView` 分离；原始结果先存档，输入视图只由原始结果生成。外部调用前保存执行标记；同轮恢复遇到无回执执行标记报告 unknown，不自动重放。明确阶段重跑维持新 execution epoch 的显式重跑语义。
- 格式锁定 ison-py 1.2.0、zon-format 1.2.3、TOON 官方 e475c82e9da03dfaf88c0b277dee6b5d17100b13（0.9.0b1）。ISON 限非空扁平对象/同构扁平记录数组；CSV 限非空同字段同顺序扁平记录数组，单元格为 JSON 标量文本经 CSV 转义以区分 null/字符串/数字。MD 使用 JSON pointer 与 JSON 值表保留层级和类型。ISON/TOON/ZON 编解码往返不能保持严格类型和值时明确报错。
- 预算用消费模型的已知 tiktoken tokenizer；未知模型启用硬预算时报 tokenizer_unavailable，不用字符估算。字段递归叶子值，整体预算重新序列化结构片段，确定性前缀不宣称保留最大长度；来源头/截取与省略说明一起计量。
- Agent 仅注册 mcp 代理（status/list/search/load/describe/call），新 schema 不枚举目录。绑定单独保存于 Agent 私有 mcp-bindings 目录，模型 workspace 只出现服务 ID/状态与来源关联；恢复和分支读原绑定。分析正文可读时，绑定缺失只影响 MCP 使用。
- 资源格式升级 v4。旧 Collector/Setter 来源没有可靠的等价 MCP/CLI 配置，明确拒绝并提示备份后重建，不能猜测迁移；旧运行不恢复执行但已有阶段正文仍可读。

验收覆盖共享层真实 stdio MCP、参数/范围/目录刷新、CLI stdout/stderr/超时、JSON 标量/去重/预算/格式、快照/恢复/Agent 分支，以及前端构建和真实浏览器。字段及整体预算中的前缀截取按用户确认使用二分查找；tokenizer 局部非单调时允许略短前缀，但接受的候选必须重新计量并满足预算。

## 实现验证（2026-09-28）

- 核心真实 stdio MCP 批次：41 passed。迁移后的 Agent、interaction、lifecycle 批次：207 passed；config、collection、mcp 批次：214 passed；Workflow 分批：74、9、34、20 passed。后端各批测试均限制在 60 秒以内。
- 前端 `npm run build`（包含 vue-tsc）通过；来源编辑器针对性单测 6 passed。`ruff check src tests`、`git diff --check` 通过。
- `openspec validate collect-from-mcp-and-cli --strict --no-interactive` 通过。
- Playwright Chromium 在新启用的 Vite `http://127.0.0.1:3018` 实测：新建 CLI argv/shell 来源、带 `arguments.value` 的 MCP echo 来源、stdio MCP 服务均 POST 201 并从 GET 列表回读一致；Workflow 六种格式和总/单项/字段 token 控件可见；资源页与 Workflow 在 390px 移动视口无横向溢出。结果和截图位于 `artifacts/collect-from-mcp-cli-browser-results.json` 及同目录。旧端口 3017 的 Vite 热更新缓存返回过旧模块，故以强制重建的 3018 实测为准。

- 用户确认预算截取采用二分查找，允许因 tokenizer 局部非单调而保留略短的前缀；每个接受候选仍经过预算计量。无需为追求最长前缀逐字符遍历。
