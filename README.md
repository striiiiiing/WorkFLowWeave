# LogAgent

Python 3.11+ 的异步采集与分析工作流。按模块的实现任务及依赖关系见
[执行计划](openspec/changes/configurable-collection-analysis-workflow/tasks.md)。
规范目录、变更流程与历史文档说明见 [OpenSpec 存放约定](openspec/README.md)。

```bash
uv sync --group dev
uv run pytest
uv run python examples/collect.py
```

当前提供 Collection、AI、Channel 与 LangGraph Workflow 的 Python 调用接口，以及 FastAPI 服务和 Vue 3 管理界面。Workflow 使用 SQLite 保存运行状态和各阶段历史，支持进程重启后恢复。前后端需要分别启动，完整命令见 [前端运行说明](frontend/README.md#开发)。

示例支持 `--collector logs --log-file app.jsonl`。

## Session 业务存档与恢复

Workflow 默认使用 `data/workflows.sqlite3`，也可注入 `SessionStore` 或指定 `database`。LangGraph checkpointer 保存执行位置；SessionStore 独立保存原配置快照、业务结果、状态、通知意图与回执。父图和子图使用同一存档节点工厂，以闭包绑定阶段和条目标识，提交业务事务后再返回图状态。重放相同逻辑写入复用原版本，冲突报错。

项目自有 SQL 存储统一使用 SQLModel 定义表、查询和事务；SQLite 仍是当前数据库，LangGraph 官方 checkpointer 管理其内部存储。SessionStore 兼容已有 `session_headers` / `session_entries` 表及数据，连接层保留 WAL、完整同步、外键、安全删除和立即事务。

`SessionView` 提供只读列表、详情和固定业务 `version` 的阶段内容，不读取 checkpoint 内部表。`BackupPolicy` 默认保存全部正文；关闭备份时正文仅在当前运行内存中使用。到期删除全部历史正文并保留摘要、可用性及幂等键，避免重放复活内容。

```python
sid = await workflow.trigger("daily")
result = await workflow.wait(sid)
record = await workflow.get_session(sid)
content = await workflow.session_view.get_phase_content(
    sid, "analyze", version=record.version,
)
```

触发返回 session 标识，RunCoordinator 持有任务，调用者取消等待不会取消运行。显式取消使用 `await workflow.cancel(sid)`；恢复使用 `await workflow.recover(sid)`，然后通过 `wait` 等待结果。恢复保留原 session 的快照和内容，缺少 checkpoint 或必要存档时明确失败，不重采或重新执行成功分析补齐。

通知先存档意图再调用渠道，回执逐项保存；已有意图但回执未知时记录 `delivery_uncertain`，不自动补发。启动将遗留运行标记为中断，不自动恢复。只支持单执行器进程；调用方注入的存储由调用方关闭。旧 Workflow 数据库需显式迁移，不能把旧记录静默隐藏在新表之外。

旧直读 SQLite CLI 已移除，对外命令行将在交互模块中通过 HTTP 查询同一 SessionView。

## 独立使用采集模块

```python
import asyncio

from logagent.collection import CollectorManager
from logagent.config import PluginRegistry, expand_source
from logagent.models import CollectionContext, SourceConfig, SystemConfig


async def main():
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(plugin_dir="plugins"))
    manager = CollectorManager(registry.collectorRegister)
    source = expand_source(
        SourceConfig(id="demo", collector="mock"),
        collector=registry.collectorRegister.get("mock"),
    )
    manager.validate(source)
    result = await manager.collect(
        source, CollectionContext(workflow_id="example", session_id="example-run")
    )
    print(result.model_dump_json(indent=2))


asyncio.run(main())
```

插件目录不存在时仍可使用内置 logs Collector；mock 由仓库中的 `plugins/mock` 提供。`report.errors` 提供逐插件的发现诊断；`manager.describe()` 返回能力、字段和完整 JSON Schema。

保存或导入来源时调用 `expand_source`：options 按 schema 默认值 → 实例显式键覆盖；Setter 按模板 → 实例显式键覆盖。同名复杂值整体替换，显式空列表有效。展开成功后 `template=None`，运行时直接使用固化的配置，不回查模板或可变插件默认值。

`CollectionContext` 只携带本次调用的运行时依赖，不持久化。Mock 通过 `plugins/mock` 注册；logs 需要已固定的 `log_path`。外部 Collector 可按需使用注入的异步凭据解析器。

## 内置采集源

| Collector | options | Setter 与行为 |
| --- | --- | --- |
| `mock` | `records`（最多 1000 条，省略使用离线样例）；`mode=success/empty/failed/timeout` | `filter` 等值过滤、`sort_by` / `descending`、`fields`、`group_by`，依次过滤、排序、投影、分组、格式化。 |
| `logs` | `max_lines=200`、`max_bytes=262144`；上限分别 10000 行 / 16 MiB | `levels`、`modules`、`session_id`、`start_time` / `end_time`、`fields`、`group_by`；按日志中的出现顺序返回。 |

Mock 的公开字段列出默认样例的键；自定义 `records` 的字段也可在 Setter 中选择。过滤要求字段存在，数字和布尔值不混同；投影后缺少分组字段时进入 null 组，分组不改变计数单位。

日志使用 UTF-8 JSONL，每个完整事件以换行结束，例如：

```json
{"time":"2026-09-13T08:00:00Z","level":"INFO","module":"collection","event":"finished","workflow_id":"daily","session_id":"run-1","message":"采集完成"}
```

logs 兼容将 `timestamp` 作为缺省的 `time`。读取从文件尾分块进行，受字节和行数预算约束；预算切开的首行与尚未写完的尾行被忽略并记录 metadata。正常追加不会扩展本次读取的固定终点；轮转、截断或损坏完整事件会报告明确错误。时间范围必须带时区，包含起止端点。

采集结果保留 `success/empty/filtered_empty/missing/failed/timeout` 的区别；只报告处理后计数。异常和非法返回不会当作空结果。外部取消继续传播，Manager 不决定 Workflow 的 stop/skip 策略。

## 自定义 Collector 插件

```text
plugins/
  config.json             # 可选；启用开关和 options 默认值
  example/
    plugin.json
    main.py
```

`plugin.json`：

```json
{"id":"example","version":"0.1.0","kind":"collector","api_version":1,"entry":{"backend":"main.py"}}
```

`main.py`：

```python
from logagent.models import CollectorOutput


class ExampleCollector:
    name = "example"
    description = "示例文本来源"
    fields = ["message"]
    count_unit = "records"
    options_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "minLength": 1, "description": "待采集文本"}
        },
        "required": ["message"],
        "additionalProperties": False,
    }
    setters_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    async def collect(self, options, setters, context):
        return CollectorOutput(
            status="success", items=[{"message": options["message"]}],
            text=options["message"], count=1,
        )


class Plugin:
    def register(self, api):
        api.register_collector(ExampleCollector())


plugin = Plugin()
```

一个入口可以注册多个同类能力。每个可配置字段必须有类型和说明，schema 使用 JSON Schema 2020-12，引用在声明内部解析。需要跨字段检查时可提供同步纯 `validate(options, setters)`，成功返回 `None`；它不能进行采集或其他 I/O。模板、配置和输出都应遵守公开 schema。

配置模块按内置能力、排序后的外部目录发现插件；禁用插件不导入，某个插件的声明失败撤销该插件的全部临时注册。只读注册表只供业务模块查询。插件是可信 Python 扩展，异步采集应可取消，阻塞 I/O 必须有实际时限。

可选的 `plugins/config.json`：

```json
{"collector":{"example":{"enabled":true}}}
```


### 实例与 Workflow 调用配置

插件作者通过构造函数注入内部依赖；`plugin.register(api)` 可自行读取
`api.config_path` 指向的插件目录 `config.json`，验证后构造能力。
框架仅解释根 `plugins/config.json` 的 `enabled`，不接受 `defaults`。
插件以现行设计文档为准直接更新；不提供旧接口兼容层或迁移机制。

实例 `SourceConfig` / `ChannelConfig` 保存一套账户及可选调用默认值。
`options_schema.properties` 中标记 `"x-logagent-workflow": true` 的字段可以被
Workflow 覆盖；未标记的连接和凭据字段只能在实例设置。Setter 是调用设置。
例如下面的字段可放入现有 Workflow 定义，两份 Workflow 可以引用同一账户：

```json
{
  "sources": ["history-account"],
  "source_overrides": {
    "history-account": {"options": {"limit": 5}, "setters": {"fields": ["session_id"]}}
  },
  "channels": ["email-account"],
  "channel_overrides": {
    "email-account": {"options": {"recipient": "report@example.com"}}
  }
}
```

options 按 schema 默认值、实例 options、Workflow options 同名键整体覆盖。
Setter 按实例模板、实例 Setter、Workflow template、Workflow Setter 覆盖；
显式空列表有效。保存 Workflow 时校验完整配置，运行快照固定合并值和路径。
渠道插件的 `create(config, credentials)` 只接收实例 options；
`send(notification, *, options)` 接收本次调用 options。邮件 recipient 属于调用层，
不同收件人复用账户连接；Mock 文件 path 属于实例层。所有渠道插件直接实现上述 send 契约。
