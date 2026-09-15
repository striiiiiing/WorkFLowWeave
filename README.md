# LogAgent

Python 3.11+ 的异步采集与分析工作流。按模块的实现任务及依赖关系见
[执行计划](openspec/changes/configurable-collection-analysis-workflow/task.md)。

```bash
uv sync --group dev
uv run pytest
uv run python examples/collect.py
```

当前提供 Collection、AI、Channel 与 LangGraph Workflow 的 Python 调用接口。Workflow 使用 SQLite 保存运行状态和各阶段历史，支持进程重启后恢复。HTTP API 与完整应用生命周期入口仍按任务计划推进。

示例支持 `--collector logs --log-file app.jsonl`。

## SQLite 保存范围与恢复

`WorkflowService` 默认复用注入的 `SQLiteResourceStore.location` 文件；未注入资源仓库或资源仓库为 `:memory:` 时，使用 `data/workflows.sqlite3`。可以传入 `database="data/logagent.sqlite3"` 或 `run_store=SQLiteRunStore(...)` 指定文件。可恢复 Workflow 不接受 `:memory:` 存储。

| 数据 | SQLite 中的内容 |
| --- | --- |
| 可复用配置 | `resources` 保存 Source、Setter、AI、Channel、Workflow；由 SQLiteResourceStore 管理。 |
| 运行快照 | `run_sessions` 保存 session、状态、阶段、时间、冻结的 WorkflowSnapshot 和日志路径。 |
| 阶段与逐项结果 | `run_stages`、`run_items` 保存 collect/analyze/aggregate/notify/finish 的结果、采集项、分析项，以及发送意图和回执。 |
| 用户可查历史 | `run_history` 保存按顺序编号的事件、时间、阶段、输入、输出及脱敏错误正文；默认完整保留，不自动删除。 |
| LangGraph 恢复点 | 原生 `AsyncSqliteSaver` 在同一 SQLite 文件中管理 `checkpoints`、`writes`。 |

数据库保存实际参与工作流的采集结果和分析正文；logs Collector 的原始日志文件仍在配置的路径中。运行时客户端、凭据解析器和解析后的凭据不进入 checkpoint 或历史。自定义 Collector 返回的正文属于运行数据，也会保存。

每次触发先冻结配置快照，恢复使用这份快照。阶段结果在图推进前提交，逐项成功结果也立即提交；`recover(session_id)`（别名 `resume`）复用已完成阶段与成功分支，重试未完成项。已完成 session 再次恢复直接返回最终结果。恢复不是自动扫描：重启后需显式调用该接口，并重新装配所需插件和运行时凭据。

通知正文在发送前固定，发送意图先于外部调用写入 SQLite。已有回执的目标在恢复时跳过；有发送意图但没有可靠回执时记为 `delivery_uncertain`，不会自动补发，其他未开始目标可继续。因此不能保证外部通知 exactly-once；需要用户核对不确定投递的实际接收情况。单个数据库文件只支持一个执行器进程，同一进程的多个服务实例会互斥执行相同 session。

## 运行并恢复一个 Workflow

在仓库根目录将下面代码保存为 `workflow_demo.py`。示例使用离线 Mock AI，通知追加到本地 JSONL 文件，配置和运行历史共用 `data/logagent.sqlite3`。

```python
import asyncio
import sys

from logagent.ai import AIService, MockProvider
from logagent.channel import ChannelManager, MockFileChannelType
from logagent.collection import CollectorManager
from logagent.config import PluginRegistry, SQLiteResourceStore, expand_source
from logagent.models import (
    AIConfig, AnalysisTask, ChannelConfig, SourceConfig, SystemConfig,
    WorkflowDefinition,
)
from logagent.workflow import WorkflowService


async def main():
    registry = PluginRegistry(builtin_channels=[MockFileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir="plugins"))
    collector = CollectorManager(registry.collectorRegister)
    ai = AIService(providers={"mock": MockProvider()})
    channel = ChannelManager(registry.channelRegister)
    with SQLiteResourceStore("data/logagent.sqlite3") as resources:
        source = expand_source(
            SourceConfig(id="demo-source", collector="mock"),
            collector=registry.collectorRegister.get("mock"),
            options_defaults=registry.collectorRegister.options_defaults("mock"),
        )
        resources.save("sources", source)
        resources.save("ai", AIConfig(id="demo-ai", provider="mock", model="offline"))
        resources.save("channels", ChannelConfig(
            id="demo-channel", channel="mock", options={"path": "data/notifications.jsonl"},
        ))
        resources.save("workflows", WorkflowDefinition(
            id="demo", sources=["demo-source"],
            analyses=[AnalysisTask(id="summary", ai="demo-ai", prompt="总结：{input}")],
            channels=["demo-channel"],
        ))
        workflow = WorkflowService(collector, ai, channel, resources)
        try:
            if sys.argv[1:] == ["recover"]:
                result = await workflow.recover("demo-run")
            else:
                result = await workflow.trigger("demo", session_id="demo-run")
            print(result.model_dump_json(indent=2))
            print(await workflow.history("demo-run", stage="analyze"))
        finally:
            await workflow.shutdown()
            await channel.stop()
            await ai.close()


asyncio.run(main())
```

```bash
uv run python workflow_demo.py
# 新进程恢复同一 session；完成过的运行不会再次采集、分析或发送。
uv run python workflow_demo.py recover
```

`session_id` 必须唯一，重新执行完整流程应使用新 ID。取消执行可调用 `await workflow.cancel(session_id)`；关闭服务会取消并等待当前任务退出，已有运行记录保留。调用方注入的 `run_store` 由调用方负责关闭。

只读 CLI 输出 JSON，支持分页和阶段筛选；数据库路径必须指向运行时使用的同一个文件：

```bash
uv run python -m logagent.workflow --database data/logagent.sqlite3 sessions --workflow-id demo
uv run python -m logagent.workflow --database data/logagent.sqlite3 show demo-run
uv run python -m logagent.workflow --database data/logagent.sqlite3 history demo-run --stage analyze --limit 100 --offset 0
```

Python 调用可使用 `await workflow.list_sessions(...)`、`await workflow.get_session(session_id)` 和 `await workflow.history(session_id, ...)` 查看同样的数据。

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
        options_defaults=registry.collectorRegister.options_defaults("mock"),
    )
    manager.validate(source)
    result = await manager.collect(
        source, CollectionContext(workflow_id="example", session_id="example-run")
    )
    print(result.model_dump_json(indent=2))


asyncio.run(main())
```

插件目录不存在时仍可使用内置 logs Collector；mock 由仓库中的 `plugins/mock` 提供。`report.errors` 提供逐插件的发现诊断；`manager.describe()` 返回能力、字段和完整 JSON Schema。

保存或导入来源时调用 `expand_source`：options 按 schema 默认值 → 插件 defaults → 实例显式键覆盖；Setter 按模板 → 实例显式键覆盖。同名复杂值整体替换，显式空列表有效。展开成功后 `template=None`，运行时直接使用固化的配置，不回查模板或可变插件默认值。

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
{"collector":{"example":{"enabled":true,"defaults":{"example":{"message":"离线文本"}}}}}
```
