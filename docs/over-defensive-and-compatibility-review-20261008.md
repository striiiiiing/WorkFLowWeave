# 过度防御与兼容冗余审查

审查及修复日期：2026-10-08。审查基线：`6c3bebb` 加当时工作区改动，包括未提交的源码。范围覆盖后端配置、采集、MCP、Agent、生命周期与渠道插件，以及前端资源编辑、运行观察和相关测试、OpenSpec。用户已要求修复 F1、F3–F6、W1、W2，F2 暂不处理；本报告保留原问题证据并记录修复结果。proposal/design 未修改。

## 结论

项目存在过度防御和兼容冗余。主要问题集中在：旧契约仍进入新模型和执行分支、兼容转换存在多份实现、用模糊异常判断触发降级、不同生命周期共享防过期门槛，以及为同一状态保留多条传递路径。

下面列出 **6 类发现**：前 4 类有最小运行复现，后 2 类是调用关系和实现结构可确认的维护问题。另列 2 项兼容收敛观察项。不能将所有 `try/except`、默认值、历史读取和协议回退都视为冗余：有明确边界、仍有实际消费者、保留原语义并显式报告失败的兼容应继续存在。

优先级含义：P1 表示已证明错误行为或执行契约不一致，应优先处理；P2 表示可确认的结构冗余，应在对应模块收敛时清理。优先级不是线上故障频率评估。

下面各项的原位置和复现描述对应修复前的审查基线；当前行为见处理状态及“已修复/修复结果”。

| 编号 | 优先级 | 问题 | 处理状态 |
| --- | --- | --- | --- |
| F1 | P1 | Collector/Setter 旧配置链保留，但正式执行装配不支持它 | 已删除旧契约，统一 MCP/CLI |
| F2 | P1 | MCP JSON 新建/编辑两套转换，编辑静默修正错误输入 | 用户指定本次不改 |
| F3 | P1 | MCP discover 用异常文本和宽泛异常类型判断兼容降级 | 已限定协议回退，单次探测与响应校验 |
| F4 | P1 | SSE 与 GET 共用 generation 门槛，丢弃有效查询结果 | 已隔离订阅与查询生命周期 |
| F5 | P2 | Agent 已发布状态通过返回值、共享列表、异常属性重复传递 | 已由当前轮次的持久化增量事件判断 |
| F6 | P2 | 无仓内执行消费者的兼容入口和不可达宽容分支 | 已删除三个入口/分支 |
| W1 | P2 | AI provider 旧别名贯穿各层 | 已在持久化读取边界归一，内部仅用正式 ID |
| W2 | P2 | retention_days 编辑器兼容分支 | 已删除旧字段提示、确认与转换 |

## F1：Collector/Setter 兼容停在配置层，正式执行链没有闭合

**位置与调用链**

- [models.py:169](/mnt/d/code/LogAgent/src/workflowweave/models.py:169)：`SourceConfig` 仍接受 `collector`/`call` 二选一，保留 `options`、`setters`、`template`；`SetterTemplate` 仍是正式模型。
- [config/store.py:49](/mnt/d/code/LogAgent/src/workflowweave/config/store.py:49)、[config/store.py:275](/mnt/d/code/LogAgent/src/workflowweave/config/store.py:275)：资源仓库仍有 setters 类型和完整旧来源校验、保存路径。
- [config/calls.py:33](/mnt/d/code/LogAgent/src/workflowweave/config/calls.py:33)：正式调用解析仍合并旧模板、Setter 和覆盖层。
- [collection/manager.py:13](/mnt/d/code/LogAgent/src/workflowweave/collection/manager.py:13)：构造参数靠 `hasattr(..., "call")` 区分 MCP runtime 与旧 registry；`collect()` 仍可转入 `_collect_legacy()`。
- [lifecycle/service.py:195](/mnt/d/code/LogAgent/src/workflowweave/lifecycle/service.py:195)：正式装配始终传入 `mcp_runtime`，因此 manager 的 `_legacy` 为 `None`；但同一组合根在第 219 行把插件 Collector registry 传给资源仓库。
- [collection/manager.py:26](/mnt/d/code/LogAgent/src/workflowweave/collection/manager.py:26)：`reload_register()` 没有实现，却仍被 [lifecycle/service.py:478](/mnt/d/code/LogAgent/src/workflowweave/lifecycle/service.py:478) 调用。

**触发与复现**

注入一个有合法 object schema 的 `old` Collector registry，保存 `SourceConfig(id="legacy", collector="old")`。资源文件保存成功，新建 ResourceStore 后也能重载。随后用正式装配形态 `CollectorManager(MCPRuntime(connector))` 采集同一来源，结果为：

```text
saved = true
reloaded = true
status = missing
error.code = collector_missing
```

这是有 Collector 插件时可触发的契约问题；不表示当前内置插件已经提供该 Collector。测试使用临时资源文件和最小 registry，没有加载远端插件或访问用户数据。

**为什么属于兼容冗余**

它保留了模型、保存、模板合并、registry、执行适配和重载外形，但这些能力在正式执行装配中并不相通。测试或直接传 registry 的旧调用可以运行，不能证明生产支持该执行形式；适配仍进入正式模型与保存入口，维护面并不窄。

**修复结果与依据**

用户明确不存在需要保留的 Collector/Setter 数据，直接删除相关实现和描述；来源按 [redesign-mcp-schema-first/design.md](/mnt/d/code/LogAgent/openspec/changes/redesign-mcp-schema-first/design.md) 的 MCP/CLI 契约执行。

`SourceConfig.call` 必填；删除 Collector/Setter 字段、资源类型、模板合并、插件注册/发现、构造形状猜测、旧执行分支、空重载入口和旧结果字段。删除针对假设历史 Collector 数据的专门分支。前端来源编辑、覆盖与插件目录同步只表达 MCP/CLI 来源及 channel/tool 插件。

采集结果只保留原始 `raw` 和执行事实，空结果统一走 `on_empty`，错误走 `on_error`。报告读取保存的 shared_input/input_views，删除输入为空时从旧 text 重建的路径，避免合法空输入触发旧字段异常。相关测试改为 MCP/CLI 调用、原始结果和冻结快照验证。

## F2：MCP JSON 兼容转换存在两份实现，错误输入被编辑路径静默改写

**位置**

- [frontend/model/mcp/import.ts:19](/mnt/d/code/LogAgent/frontend/src/modules/resources/model/mcp/import.ts:19)：前端根别名选择和 JSON 转换。
- [MCPServerEditor.vue:55](/mnt/d/code/LogAgent/frontend/src/modules/resources/ui/MCPServerEditor.vue:55)：新建调用后端 `importMcpServers`；编辑调用前端 `serverToResource` 后再 `replace`；切换回字段模式也调用前端转换。
- [models.py:245](/mnt/d/code/LogAgent/src/workflowweave/models.py:245)：后端 `MCPServerImportEntry`；第 274 行起为根包络及别名校验。

**运行对照**

使用相同的合法 stdio 服务、仅替换下表字段。后端直接运行 `MCPServerImportConfig.model_validate(...).to_resources()`，前端运行实际 `serverToResource()`：

| 输入 | 后端新建转换 | 前端编辑转换 | 影响 |
| --- | --- | --- | --- |
| `enabled: "false"` | 接受并得到 `false` | 得到 `true` | 同一 JSON 在新建和编辑时启停语义相反 |
| `timeout: "oops"` | 拒绝 | 静默变为 `60` | 无效值被默认值掩盖 |
| `cwd: 123` | 拒绝 | 静默变为 `null` | 用户指定的工作目录被丢弃 |
| 额外字段 `unused_field: 1` | 拒绝 | 字段被丢弃 | 拼写错误或不支持的参数不再可见 |

此外，`parseMcpConfig()` 对同时存在的 `servers` 和 `mcpServers` 使用 `??` 选择前者，实测只保留 `servers` 的服务。后端原始包络明确拒绝二者同时出现，但 UI 在提交前已经去掉另一个键，后端无法再发现冲突。此项同时影响 UI 新建与编辑。

**为什么属于过度宽容兼容**

根别名和 `http → streamable_http` 的兼容有明确需求；问题在于转换顺带接受错误类型、过滤未知字段，并用默认值将错误输入变成合法资源。后端 replace 的严格校验无法恢复转换时已丢失的信息。缺失字段使用默认值，与字段已经提供但类型错误应报错，是不同情况。

[support-cursor-mcp-config/design.md:5](/mnt/d/code/LogAgent/openspec/changes/support-cursor-mcp-config/design.md:5) 要求边界解析后得到统一资源，第 9 行明确要求完整校验；新建/编辑使用不同接口本身符合设计，不能为了减少接口而改成两份行为不同的宽容转换。

**建议**

统一外部 JSON 的校验和归一规则：拒绝根别名冲突、错误字段类型及未知字段，只对真正缺失的字段应用有依据的默认值。新建、编辑与切换表单模式应遵循同一转换契约；可保留不同保存接口，但不要让每条路径分别解释兼容语义。为上述同输入不同结果补充契约对照验证。

## F3：MCP discover 降级依据过宽，真实错误被报告为健康

**位置**：[mcp/runtime.py:139](/mnt/d/code/LogAgent/src/workflowweave/mcp/runtime.py:139)，重点为第 152 行的异常分流。

`discover()` 抛出任意 `AttributeError`、`NotImplementedError`，或异常文本包含 `method`、`unsupported`、`unknown` 时，就执行 `tools/list`。这既包含“不支持该方法”，也包含 discover 内部代码缺陷、未知鉴权错误等完全不同的失败。

**最小复现**

会话提供真实 `discover()` 方法，分别抛出：

```python
RuntimeError("unknown authentication failure")
AttributeError("bug inside discover")
```

`list_tools()` 返回一个合法工具。对两个会话执行实际 `MCPRuntime.probe()`，均得到 `status="healthy"`，且 `list_tools` 调用一次。discover 的失败不在健康结果中体现。

**影响**

真实故障被解释成旧协议兼容，目录刷新可以成功并清除错误状态，排障时只看到健康。此外，discover 位于分页循环内部；已确认不支持 discover 的服务在每个 tools/list 分页仍会被再次尝试，兼容探测成本随分页增加。

**设计依据与建议**

[redesign-mcp-schema-first/design.md:28](/mnt/d/code/LogAgent/openspec/changes/redesign-mcp-schema-first/design.md:28) 明确要求服务未声明或返回“不支持”时回退，回退本身应保留。收窄为可识别的协议错误码/能力结果；如果要适配没有 discover 方法的注入对象，在调用前显式检查该方法，不能把方法内部的 AttributeError 一并吞掉。每次连接只判断一次能力，再沿选定协议完成分页；其余错误显式传播并记为失败。

**已修复**：runtime 只将无 discover 方法或 MCP `METHOD_NOT_FOUND` 作为回退条件，一次 discover 后完成 tools/list 分页。响应使用 SDK ListToolsResult 校验；内部异常、鉴权、参数错误及 malformed 响应均报告 unhealthy。Python MCP SDK 对未知方法返回特定的 `INVALID_PARAMS / Invalid request parameters / data=""`，仅由 SDK transport 适配层精确归一为 METHOD_NOT_FOUND；带具体错误数据或其他文本的参数错误继续失败。该签名及真实 stdio 服务均纳入回归。

## F4：SSE 生命周期的防过期门槛误伤同会话 GET

**位置**：[useSession.ts:25](/mnt/d/code/LogAgent/frontend/src/modules/runs/composables/useSession.ts:25)、第 47 行查询、第 111 行订阅错误、第 121 行主动刷新。

`closeConnection()` 每次递增 `generation`。GET 结果除了 AbortSignal 和 request identity，还检查 `owner === generation`；SSE 报错只关闭连接，也会改变 GET 所依赖的 generation。

**实际 composable 复现顺序**

1. 对会话 `one` 调用 `refresh()`，启动订阅和尚未完成的 GET。
2. GET 未返回时，当前订阅调用 `handlers.error(new Error("SSE failed"))`。
3. GET 成功返回同会话、较新版本的完整快照，关键字段为 `{ session_id: "one", version: 8, status: "running" }`。
4. 等待 refresh 完成：GET signal 的 `aborted=false`，`data` 仍为 `undefined`，查询 `error` 为空，仅 `connectionError="SSE failed"`。

复现加载并运行实际 Vue composable，未复制其实现。没有切换会话、取消查询或卸载组件。

**为什么属于过度门控**

会话切换/卸载隔离、取消旧请求和拒绝低版本快照都有必要；问题是把“订阅已失效”当成“所有读取均已失效”。因此用户用于恢复页面的主动查询也会丢失，额外门槛降低了可靠性。

[redesign-workflow/design.md:190](/mnt/d/code/LogAgent/openspec/changes/redesign-workflow/design.md:190) 要求切换会话和释放作用域时隔离旧连接/查询，并保留手动同步；不要求 SSE 关闭时废弃同会话的有效 GET。

**建议**

分清会话、订阅与请求的所有权：SSE generation 只隔离 SSE 回调，GET 由会话身份、取消和当前请求身份判断是否有效，快照仍按版本接收。补测“GET 未完成时 SSE 失败”和“SSE 终态关闭后 GET 返回”，保留现有路由切换、作用域释放和低版本响应测试。

**已修复**：订阅使用 connectionGeneration；GET 仅按当前会话、AbortSignal 和当前请求身份接收结果。保留响应 session_id 校验与版本比较；新增 SSE 错误、终态关闭及同一 tick 路由切换的回归。

## F5：Agent 已发布标志通过三条路径传递，又防御性吞掉属性写入异常

**位置**：[runtime/stream.py:45](/mnt/d/code/LogAgent/src/workflowweave/agent/runtime/stream.py:45)、[runtime/runner.py:77](/mnt/d/code/LogAgent/src/workflowweave/agent/runtime/runner.py:77)、[runtime/runner.py:223](/mnt/d/code/LogAgent/src/workflowweave/agent/runtime/runner.py:223)。

同一个“已发布增量”事实同时存在于：

- stream 局部 `published`，成功时通过返回元组传给 runner。
- runner 传入的可变单元素列表 `publication=[False]`，每次增量同步写入。
- 发生异常时动态挂到 `exc._agent_published`，挂载失败用 `except Exception: pass` 吞掉。

runner 对取消读取列表，对超时和普通异常再做 `getattr(exc, ..., published or publication[0])`。正式调用已经传入共享列表，异常私有属性再次传递同一事实属于重复机制；异常对象是否允许动态属性也变成了不必要的分支。

**影响与证据边界**

这增加了维护同步状态、理解不同异常路径的成本。当前没有复现出 partial 标记错误，因此此项是结构冗余，不是已证实的事件丢失。`partial` 本身必须保留：[test_service.py:346](/mnt/d/code/LogAgent/tests/agent/test_service.py:346) 已有流式失败后保留已发布增量、不得重复执行的用例。

**建议**

以一个明确的 turn/stream 状态对象保存发布事实，所有成功、异常、取消路径读取同一份状态；不再动态修改异常对象或保留列表、返回值、异常属性三重传递。保留“增量已发出后失败”的测试，验证取消、空闲超时与总超时的 partial 语义。

**已修复**：当前轮次的持久化 message.delta 事件是唯一发布事实；取消、超时和错误都回读同一事件日志判断 partial。删除局部标志、返回元组、共享列表和异常私有属性，不另存布尔状态。回归覆盖有/无增量时的失败、取消、空闲超时和总超时，以及“写入失败”和“写入已提交但调用尚未返回时取消”的窗口，不重试、不重复发布。

## F6：无仓内消费者的兼容入口和不可达宽容分支

引用检索覆盖 `src`、`frontend/src`、`plugins`、`tests`、`examples`、`docs`、README 和 pyproject；下面的“无调用”仅指上述仓内执行代码，不能证明不存在仓外使用者。

| 原位置 | 冗余表现 | 修复结果 |
| --- | --- | --- |
| `channel/unified_queue_manager.py` | 仅将 `UnifiedQueueManager` 设为 `UnifiedQueue` 别名；无仓内消费者 | 已删除文件，统一 UnifiedQueue |
| [runtime/builder.py](/mnt/d/code/LogAgent/src/workflowweave/agent/runtime/builder.py) | `create_graph()` 无仓内调用，每次新建 GraphBuilder | 已删除函数及出口，保留组合根 GraphBuilder |
| [telegram/channel.py](/mnt/d/code/LogAgent/plugins/channel/telegram/channel.py) | `_call(..., missing_ok=False)` 中静默成功分支无调用 | 已删除参数和静默返回，SDK 方法缺失继续明确报错 |

[redesign-agent-module/design.md:201](/mnt/d/code/LogAgent/openspec/changes/redesign-agent-module/design.md:201) 要求组合根编译一次静态 graph，第 351 行明确内部迁移完成后不保留长期 re-export，真实外部依赖应先记录，不能猜测存在。兼容入口仅标注“外部调用者”而未列出使用证据，不能成为长期保留两套入口的充分依据。

这些条目主要影响代码复杂度和维护，并未证明当前生产通过这些入口执行了错误行为。

## 兼容收敛观察项

### W1：AI provider 旧别名传播到了校验、装配和 UI（已修复）

[ai/options.py:9](/mnt/d/code/LogAgent/src/workflowweave/ai/options.py:9) 同时识别 `http` 与 `openai_compatible_api`；[lifecycle/service.py:203](/mnt/d/code/LogAgent/src/workflowweave/lifecycle/service.py:203) 注册两个同类型 factory；[AIProviderEditor.vue:68](/mnt/d/code/LogAgent/frontend/src/modules/resources/ui/AIProviderEditor.vue:68) 编辑旧值时继续保留 `http`。

旧别名确有记录：[frontendFix/task.md](/mnt/d/code/LogAgent/openspec/changes/archive/frontendFix/task.md) 曾要求保留，并记录旧后端只能接受 `http`。用户本次要求收敛：持久化资源与运行快照读取边界统一转换为 `openai_compatible_api`；资源归一后原子写回，转换不修改调用方数据且可重复执行。新 API 校验、factory 装配和 UI 仅用正式 ID，前端不再保留或再次转换旧别名。

### W2：retention_days 编辑器兼容分支（已删除）

[backup.ts](/mnt/d/code/LogAgent/frontend/src/modules/workflows/model/create/backup.ts) 和 BackupMatrix 原有旧策略提示、确认与清理路径，当前配置模型不接受 `retention_days`。按用户本次决定删除编辑器中的该字段及 hasLegacyRetention/classifyLegacyRetention 分支，直接编辑四类当前保留期限，不再要求旧策略确认。

已有归档的保存期限有实际数据语义，[_deadline()](/mnt/d/code/LogAgent/src/workflowweave/workflow/storage/retention.py) 继续读取原截止日期。用户本次变更的是编辑器配置分支，记录在新任务中，不修改设计文件或已有归档期限。

## 有依据的防御和兼容，本次不列为问题

| 机制 | 保留理由 |
| --- | --- |
| MCP 明确不支持 discover 时回退 tools/list | 设计明确要求；F3 只针对触发条件过宽和重复探测 |
| QwenPaw manifest 在配置边界归一 | [remote-workflow-deployment-plugin-compat/design.md:25](/mnt/d/code/LogAgent/openspec/changes/remote-workflow-deployment-plugin-compat/design.md:25) 明确兼容外部格式并拒绝冲突；不能与 F1 的执行装配问题混为一谈 |
| config/migrations 的持久化版本迁移与冲突拒绝 | 兼容集中在边界，明确版本及不可迁移语义 |
| 已保存归档正文、归档期限和 Agent 提示词 | 这些是当前存储事实和正常恢复语义，不是旧来源执行兼容 |
| 超时、取消传播、进程组清理和工具任务清理 | 管理真实资源所有权；清理时容忍已退出进程有具体原因 |
| 外部输入 schema 校验、响应身份校验与快照版本比较 | 有系统边界和一致性依据；F4 针对不同生命周期共用门槛 |
| 插件隔离与渠道不确定送达状态 | 显式报告失败/不确定，不是将错误伪装成成功 |

飞书 SDK 适配和渠道协议处理也被检查过，但本次没有足够证据证明其包导入 shim 或响应适配可以安全删掉，未按文件复杂或 `getattr` 数量认定冗余。

## 验证记录与限制

最小复现脚本位于 `/tmp/logagent_defensive_review_backend.py` 和 `/tmp/logagent_defensive_review_frontend.mjs`，均成功执行。后端使用临时目录、最小插件 registry 和注入式 MCP 会话；前端通过 Vite 加载实际模块，使用 Vue effectScope、延迟 GET 与订阅错误回调。它们证明具体分支和转换结果，不代表真实 MCP 鉴权或浏览器网络故障端到端已验收。

定向验证结果：

- 后端配置、来源、采集、集成、恢复、生命周期、API、Agent、渠道和 MCP 分组均通过；其中 MCP/CLI 与配置集成 `322 passed`，Agent/渠道集 `70 passed`，生命周期/API 集 `78 passed`，进程强退恢复 `4 passed`，工作流恢复选定集 `44 passed`，MCP stdio/健康/工作流集 `26 passed`。
- Agent 流式失败、取消、空闲/总超时及“增量已持久化但取消”窗口 `37 passed`；Python `compileall`、`ruff --ignore I001`、`git diff --check` 通过。
- 前端定向回归、快照订阅、来源编辑、插件目录、报告状态等通过；`vue-tsc --noEmit`、架构检查和 Vite production build 通过。Python wheel 构建产物为 `/tmp/logagent-contract-build/workflowweave-0.1.0-py3-none-any.whl`。

未执行全量测试和外部 AI 真实调用验收；本地 `19026` 端点返回鉴权失败，因此相关网络测试按其真实失败契约保留，未改成跳过或 mock 成功。F2 保持未改。保留的边界是外部 schema、响应身份/快照版本、MCP 明确不支持 discover 的回退，以及资源清理和不确定送达状态。
