# LogAgent

Python 3.11+ 的异步采集模块。按模块的实现任务及依赖关系见
[执行计划](openspec/changes/configurable-collection-analysis-workflow/task.md)。

```bash
uv sync --group dev
uv run pytest
uv run python examples/collect.py
```

本轮实现 collection 及其插件注册、只读存档前置能力；完整资源存储、Workflow、AI、通知和 API 将按任务计划继续实现。

示例也支持 `--collector logs --log-file app.jsonl`，或 `--collector history --history-workflow daily --data-dir data`。读取不存在的历史目录返回真实空结果。

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

插件目录不存在时仍可使用三个内置 Collector。`report.errors` 提供逐插件的发现诊断；`manager.describe()` 返回能力、字段和完整 JSON Schema。

保存或导入来源时调用 `expand_source`：options 按 schema 默认值 → 插件 defaults → 实例显式键覆盖；Setter 按模板 → 实例显式键覆盖。同名复杂值整体替换，显式空列表有效。展开成功后 `template=None`，运行时直接使用固化的配置，不回查模板或可变插件默认值。

`CollectionContext` 只携带本次调用的运行时依赖，不进入 JSON 或存档。Mock 无需外部依赖；logs 需要已固定的 `log_path`；history 需要注入 `FileArchiveReader(data_dir)`。外部 Collector 可按需使用注入的异步凭据解析器。

## 内置采集源

| Collector | options | Setter 与行为 |
| --- | --- | --- |
| `mock` | `records`（最多 1000 条，省略使用离线样例）；`mode=success/empty/failed/timeout` | `filter` 等值过滤、`sort_by` / `descending`、`fields`、`group_by`，依次过滤、排序、投影、分组、格式化。 |
| `logs` | `max_lines=200`、`max_bytes=262144`；上限分别 10000 行 / 16 MiB | `levels`、`modules`、`session_id`、`start_time` / `end_time`、`fields`、`group_by`；按日志中的出现顺序返回。 |
| `history` | `workflow_id`；`artifact=final`、`limit=1`；可选 `start_time` / `end_time`、`token_budget`、`overflow=truncate/error` | 仅选择终态且非当前 session；不提供 Setter，阶段正文以整个 session 为一条记录。 |

Mock 的公开字段列出默认样例的键；自定义 `records` 的字段也可在 Setter 中选择。过滤要求字段存在，数字和布尔值不混同；投影后缺少分组字段时进入 null 组，分组不改变计数单位。

日志使用 UTF-8 JSONL，每个完整事件以换行结束，例如：

```json
{"time":"2026-09-13T08:00:00Z","level":"INFO","module":"collection","event":"finished","workflow_id":"daily","session_id":"run-1","message":"采集完成"}
```

logs 兼容将 `timestamp` 作为缺省的 `time`。读取从文件尾分块进行，受字节和行数预算约束；预算切开的首行与尚未写完的尾行被忽略并记录 metadata。正常追加不会扩展本次读取的固定终点；轮转、截断或损坏完整事件会报告明确错误。时间范围必须带时区，包含起止端点。

history 按创建时间倒序选择，同时间按 session ID 倒序；次数和时间范围取交集。collection 取 `shared_input`，analysis 按声明顺序取成功分支，final 只消费冻结输出。预算按包含来源标记的最终文本 UTF-8 字节数估算，metadata 的算法为 `utf8_bytes_v1`，不表示模型提供商的实际 token 数。截取只保留能容纳的最新完整记录前缀；首条过大为 `filtered_empty`，不会跳过它寻找更小的旧记录。

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

## 只读存档接口

`FileArchiveReader(data_dir)` 读取已有 `data_dir/sessions/<session_id>/` 下的文件，公开 `get/list/load_artifact/availability`，不创建、修复或恢复运行。`record.json` 是带显式 `format_version: 1` 的 `SessionArchiveEnvelope`；`snapshot.json`、`collection.json`、`analysis.json`、`final.json` 直接保存相应契约对象。SHA-256 和 size 均针对实际 UTF-8 文件字节，snapshot 的摘要还必须匹配封套中的 `snapshot_sha256`。

正文只有通过备份策略、索引、期限、大小、摘要和结构检查才可用。未备份、范围排除、未生成、缺失、过期、损坏、写入失败各有独立原因；孤立文件不被自动视为成功备份。记录默认限 1 MiB，正文默认限 16 MiB，可在构造 Reader 时调整。文件读取使用工作线程和目录文件描述符；当前实现面向 Linux / WSL 等支持这些文件操作的平台。

完整 ArchiveStore 的写入、锁协调及过期维护属于后续任务。测试通过临时目录中的 v1 存档验证实际读取行为。
