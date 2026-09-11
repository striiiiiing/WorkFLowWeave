# 交互模块设计（v0.1）

依据：[模块 proposal](./proposal.md)、[根 proposal](../../proposal.md) §2.1、§3，以及[根设计](../../design.md) §3.1–§3.7、§4。首版使用 FastAPI、Typer 与 uvicorn，外部资源以 JSON 表达。

## 1. 职责与结构

API 接收配置、触发和查询请求，完成传输层解析后交给业务模块。CLI 的业务操作调用 HTTP API；启动与生成离线样例是两个本地命令。Channel 的后续控制入口可以直接复用内部应用服务，无须通过 HTTP 回环。

| 文件 | 职责 |
| --- | --- |
| `logagent/api.py` | 路由、请求/响应模型、依赖获取和错误映射。 |
| `logagent/cli.py` | Typer 命令、HTTP 客户端、终端输出和退出码。 |
| `logagent/app.py` | 应用工厂、依赖装配、lifespan 和 uvicorn 启动入口。 |
| `logagent/models.py` | 复用公共模型，API 不再维护另一套业务字段。 |

导入模块不得启动调度器、打开模型连接或执行 Workflow。默认单进程运行；多个 uvicorn worker 不共享调度锁，首版服务启动入口固定使用一个 worker。

## 2. 技术选型（ADR）

## 3. HTTP 与校验契约

### 3.1 资源 API

所有路由使用 `/api` 前缀。`kind` 仅允许 `sources/setters/ai/channels/workflows`，请求模型拒绝未知顶层字段。资源 ID 遵循根设计的 1–80 位字母、数字、下划线或短横线规则。

| 方法和路由 | 行为 | 成功响应 |
| --- | --- | --- |
| `GET /api/{kind}` | 列出对应资源。 | 200，资源列表。 |
| `POST /api/{kind}` | 校验并创建；ID 已存在返回冲突。 | 201，保存后的资源。 |
| `GET /api/{kind}/{id}` | 读取独立资源副本。 | 200，资源对象。 |
| `PUT /api/{kind}/{id}` | 完整替换已有资源；路径与 body ID 必须一致。 | 200，保存后的资源。 |
| `DELETE /api/{kind}/{id}` | 删除未被配置资源引用的对象。 | 204，无响应 body。 |
| `GET /api/plugins` | 查询 Collector/Channel 能力、配置 schema 和发现错误。 | 200，能力描述。 |

资源不存在时读、改、删返回 404；创建重复、删除仍被引用资源返回 409。Workflow 创建与修改调用 `WorkflowService.save()`，其余资源也须先完成所属业务模块的校验，再调用 ResourceStore，不能直接把合法 JSON 当成合法业务配置。

| 资源 | 保存前语义校验 |
| --- | --- |
| Source | Collector 存在；options/Setter 符合声明；模板存在且属于相同 Collector；合并后仍有效。 |
| Setter | Collector 存在；Setter 字段及值符合该 Collector schema，不添加未声明能力。 |
| AI | `AIService.validate()` 检查提供方、参数、工具引用、URL 与超时，不请求真实模型。 |
| Channel | `ChannelManager.validate()` 检查实例选项、通知能力、超时和重试次数。 |
| Workflow | 完整检查来源、展开后的 Setter、所有分析与 fan-in AI、目标 Channel、顺序和策略。 |

资源变更不能留下失效引用；会影响已引用资源的 Collector/模板等变更，在一致性写入边界检查其影响。删除检查和保存须与 ResourceStore 的并发写入保护协调，避免先校验后被另一请求删除引用。正在运行的 session 使用快照，不受新版本资源影响。

插件发现失败会展示可识别的诊断，其它有效插件仍可使用。`/plugins` 仅返回能力和脱敏错误，不暴露凭据、任意宿主路径或可执行远程代码的入口。

### 3.2 触发、运行和备份 API

| 方法和路由 | 行为 | 成功响应 |
| --- | --- | --- |
| `POST /api/workflows/{id}/run` | 通过统一入口触发一次运行，不接受临时业务配置覆盖。 | 202，SessionRecord。 |
| `GET /api/sessions` | 可按 `workflow_id` 过滤，并接受有界正整数 `limit`。 | 200，运行记录列表。 |
| `GET /api/sessions/{id}` | 查询阶段、终态、摘要、投递结果及恢复材料。 | 200，SessionRecord。 |
| `GET /api/sessions/{id}/artifacts/{name}` | 读取 `snapshot/collection/analysis/final` 之一。 | 200，对应 JSON 存档。 |
| `POST /api/sessions/{id}/resume` | 校验原快照与材料后恢复原 session。 | 202，SessionRecord。 |
| `POST /api/sessions/{id}/cancel` | 取消并等待取消状态写回。 | 200，SessionRecord。 |
| `GET /api/health` | 查询服务是否就绪及启动诊断摘要。 | 200，健康状态；不可用时 503。 |

接受触发/恢复时设置 `Location: /api/sessions/{id}`。API 不在请求生命周期内等待模型执行完成，也不把分析失败改成触发请求的 500；后续业务错误属于 session。

`artifacts/{name}` 是固定枚举，不能用路径穿越或任意文件名读取磁盘。未知 session 返回 404；已知 session 的内容因关闭、过期、缺失、损坏而不可用时返回 409，并给出原因与可用范围；底层存档服务不可用返回 503。

`resume` 不能替换来源、AI、模板或 Channel，不能携带“使用最新配置”选项。缺少必要材料、重复恢复活动 session 或恢复无待办的完成记录返回 409。final 已冻结时只补失败通知；重新分析通过新 `/run` 创建 session。

`snapshot` 存档以公共 `WorkflowSnapshot` 序列化，包含原 `workflow`、按 ID 索引的 `sources/ai/channels` 及 `created_at`；Source Setter 已展开，凭据仍为环境变量引用。API 不在读取快照时使用最新资源填补字段。

路由注册应保证 `/plugins`、`/sessions`、`/health` 等固定路由不会被通用 `/{kind}` 路由吞掉；非法资源种类返回明确校验或不存在错误。

### 3.3 错误格式

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Workflow 配置无效",
    "details": {
      "errors": [
        {"path": ["analyses", 0, "ai"], "reason": "引用的 AI 配置不存在"}
      ]
    }
  }
}
```

统一映射 Pydantic 请求校验与 `LogAgentError`，保留可修正字段路径；执行错误写入 session 时复用结构化错误信息。响应不返回任意堆栈、凭据或完整认证头。

| HTTP 状态 | 条件 |
| --- | --- |
| 422 | 不完整/未知字段、类型范围错误、无效 schema、Workflow 语义无效。 |
| 404 | 请求直接定位的资源或 session 不存在。 |
| 409 | ID 重复、引用冲突、状态冲突、恢复材料不足或阶段内容不可用。 |
| 429 | 有界执行队列容量不足。 |
| 503 | 管理存档不可用、服务尚未就绪或正在关闭。 |
| 500 | 未预期内部错误，返回脱敏错误与可关联诊断标识。 |

Workflow 内部引用不存在属于配置错误 422；用户直接请求不存在的 Workflow 则是 404。错误消息须区分这两种情况。

## 4. CLI 契约

```text
logagent serve --config config.json
logagent init --directory ./example
logagent resource list sources
logagent resource show ai review_model
logagent resource save workflows workflow.json --create
logagent resource delete sources unused_source
logagent run daily_review
logagent sessions --workflow daily_review
logagent session SESSION_ID
logagent artifact SESSION_ID final
logagent resume SESSION_ID
logagent cancel SESSION_ID
```

业务命令共享 `--api-url`，默认 `http://127.0.0.1:8000`，可由 `LOGAGENT_API_URL` 覆盖；HTTP 请求设置连接与响应超时。`resource save --create` 使用 POST，否则使用 PUT；本地只读取 JSON 和必要的 ID，不重做来源 schema 或 Workflow 校验。

`serve` 调用应用工厂和 uvicorn；`init` 生成系统配置、Mock 来源、Mock AI、文件通知和样例 Workflow，默认不覆盖已有文件。样例完全离线，不包含真实地址、账户或秘密。

CLI 成功输出 JSON 到 stdout，错误写 stderr；成功退出 0，本地输入及 API 4xx 错误退出 2，连接或服务错误退出 1。触发成功不宣称 Workflow 已完成；用户通过 session 查询业务终态。CLI 不读取存档目录来绕过 API。

## 5. 应用装配与生命周期

### 5.1 启动

`create_app(config_path) -> FastAPI` 创建应用并配置 lifespan；依赖实例放在明确的应用容器中，路由通过依赖注入获取，不在模块全局保存一个跨测试共享的运行器。

1. 读取并校验 SystemConfig，相对目录以配置文件所在位置解析；配置无效则启动失败。
2. 初始化日志、ResourceStore、ArchiveStore，确认管理记录可读写并扫描异常结束的 session。
3. 注册内置 Collector/Channel/工具，从插件目录发现扩展；收集文件级错误，保留其它有效插件。
4. 创建共享异步 HTTP 客户端、AIService、CollectorManager、ChannelManager，并注入 WorkflowService。
5. 启动 Channel 生命周期和受控调度器，标记应用已就绪。只有装配成功后才接受业务触发。

模型客户端创建不代表调用模型；插件发现不触发采集；Channel 启动不发送测试通知。加载失败的可选插件只影响该插件，系统配置或管理存档不可用则不能把服务标为健康。

### 5.2 关闭和后台任务

关闭先标记停止接收，阻止新触发并停调度，再执行 `WorkflowService.shutdown()` 取消/等待运行，随后 `ChannelManager.stop()`、关闭模型 HTTP 客户端并结束日志等资源。使用退出栈保证启动中途失败也释放已创建资源。

所有 `create_task` 都登记到所属服务，异常必须被消费并记录，取消后的任务必须 await 回收。HTTP 断开不取消已经接受的 Workflow；用户取消通过专用 API 完成。程序导入、重复 lifespan 和测试销毁不得留下后台调度器。

每个网络或阻塞操作具有自身超时，关闭等待有界。工作线程中的 SMTP/文件操作不能被协程取消强行撤销；网关负责记录不确定结果，运行器确保取消后不启动下一条通知。硬退出后的未结束记录在下次启动标为 `interrupted`，等待显式恢复。

应用采用 asyncio 协程等待和工作线程文件 I/O，不在 async 路由直接执行阻塞磁盘或 SMTP 调用。首版默认绑定回环地址；复杂认证服务、浏览器前端、Webhook 和双向交互留到相应后续版本。

## 6. 验收与依赖

测试建议位于 `tests/test_api.py`、`tests/test_cli.py`、`tests/test_app.py`，使用 FastAPI 测试客户端、Typer Runner、临时目录和 Mock HTTP/SMTP。

- 各资源增删改查覆盖重复 ID、未知字段、路径/body ID 不一致、引用冲突及全部业务 schema；失败请求不产生半配置资源。
- 无效 Setter、模型参数、Channel 能力和 fan-in 顺序均在保存时返回带路径的 422。
- 触发及时返回 202 和 session 链接；异步失败可从 session 查询，容量超限为 429。
- 备份关闭、损坏和过期有可理解原因；非法存档名称与路径不能读取任意文件。
- 恢复使用原快照、跳过成功通知；材料不足返回 409；取消之后没有新的通知发生。
- CLI 的业务命令实际调用 HTTP 客户端，不调用 WorkflowService 或直接操作资源目录；错误退出码与 API 结果对应。
- `init` 的样例可离线贯通采集、分析、文件通知和查询，不覆盖已有用户文件。
- lifespan 正常启动/关闭和部分初始化失败都释放资源，后台异常有记录，关闭后无遗留任务。
- 十分钟稳定性运行使用真实本地 API 与离线 Mock，记录 CPU、RSS、磁盘及未处理异常，验收报告据实际运行结果填写。

依赖其余六个模块的稳定契约以及公共错误模型。交互层可以先通过 Mock 服务验证协议；最终集成必须使用真实模块装配验证资源语义和生命周期，不能只依靠路由级替身测试。
