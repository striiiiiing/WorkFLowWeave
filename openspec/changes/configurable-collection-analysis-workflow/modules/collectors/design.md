# 数据采集模块设计（v0.1）

本文细化 [proposal.md](../../proposal.md) §2.1「数据采集模块」及 [根 design.md](../../design.md) §3.1、§3.3。公共数据模型统一位于 `logagent/models.py`；本文不另定义同名的来源或结果模型。

## 1. 职责与边界

数据采集模块负责发现 Collector、说明可配置能力、验证来源实例与 Setter，以及将单个来源转换为带计数和状态的 `CollectionResult`。首版内置 `mock`、`history`、`logs`，第三方 Collector 使用相同注册入口。

| 本模块负责 | 协作模块负责 |
| --- | --- |
| Collector 类型、插件声明、来源专属 schema | 配置模块保存 `SourceConfig`、`SetterTemplate` 并解析资源引用 |
| 单来源的字段选择、过滤、排序、分组、格式化和计数 | Workflow 决定来源顺序、跨来源拼接、计数说明及共享输入 |
| 区分失败、超时、缺失、原始空和处理后空 | Workflow 根据 `on_error/on_missing/on_empty/on_filtered_empty` 决定停止或跳过 |
| 将已存档内容读成历史条目 | Archive 保存、检索、校验和标记内容可用性；Workflow 决定恢复 |

根目录 [通道注册表模块解读.md](../../../../../通道注册表模块解读.md) 中“注册表负责类型发现，管理器负责实例”的职责分离也用于采集器。Collector 不继承线程、消息队列或服务运行时。QwenPaw 的会话队列、命令优先级和 Agent 消费流程不属于采集操作。

## 2. 子模块与依赖

| 计划文件 | 职责 |
| --- | --- |
| `logagent/collectors/base.py` | `BaseCollector`、`CollectionContext`，轻量声明及格式化、计数扩展点 |
| `logagent/collectors/registry.py` | 类型注册、能力描述、按文件暂存和提交插件注册 |
| `logagent/collectors/manager.py` | `CollectorManager`，配置校验、调用、超时及状态转换 |
| `logagent/collectors/setters.py` | 已声明的字段、过滤、排序、分组操作及稳定格式化助手 |
| `logagent/collectors/mock.py` | 有限 JSON 数据的离线采集器 |
| `logagent/collectors/history.py` | 从 Archive 读取指定 Workflow 历史及执行范围选择 |
| `logagent/collectors/logs.py` | 工具运行日志的有界尾部读取 |
| `tests/test_collectors.py` | 内置来源、Setter、计数、超时及取消验收 |
| `tests/test_collector_plugins.py` | 插件发现、schema 和注册原子性验收 |

本模块可以依赖公共模型、Archive 的读取入口和标准日志接口；不依赖 Workflow 执行器、API、Channel 或模型服务。上下文通过依赖注入传入，不在插件中构造第二套 ArchiveStore。

## 3. 技术选型（ADR）

暂不填写。

## 4. 公共接口

### 4.1 BaseCollector 与上下文

```python
class BaseCollector:
    name: str
    options_model: type
    setters_model: type

    async def collect(self, options, setters, context) -> list[dict]: ...
    def count(self, items) -> int: ...

class CollectorManager:
    def register(self, collector): ...
    def discover(self, path, plugin_config): ...
    def describe(self): ...
    def validate(self, source): ...
    async def collect(self, source, context) -> CollectionResult: ...
```

`register(collector)` 接收声明完整的具体 Collector 实现；名称在同一个 Manager 中唯一。注册表保存实现类型及 schema，Manager 为执行取得独立的 Collector 对象。插件不可通过全局可变字段保存“当前来源”“上次输入”等跨运行状态。

`CollectionContext` 提供 Archive 的只读调用入口和已解析的工具日志路径，并携带用于关联日志的 Workflow/session 标识。它不提供任意资源写入或重新触发 Workflow 的快捷入口。测试可注入替代 Archive 和临时日志路径。

`collect()` 返回本次来源范围内、执行通用 Setter 前的记录，每条必须是可 JSON 序列化的字典。`options`、`setters` 都是校验后的独立值；Collector 可用 Setter 辅助查询，但不能提前丢弃记录又将其伪装成处理前计数。来源内容不得是共享的可变缓存对象。

基类只提供默认计数和格式化助手，不包含调度、重试、持久化和接收循环。`count(items)` 默认返回条目数量；覆盖它的插件需在能力描述中说明计数单位。原始和处理后计数使用同一种单位，必须为非负整数。自定义格式化可覆盖通用文本表示，但不能引入网络调用或在格式化时重新采集。

### 4.2 Manager 的输入和输出

| 接口 | 语义 |
| --- | --- |
| `discover(path, plugin_config)` | 启动阶段扫描指定目录，逐文件隔离失败，返回或保留可查询的发现诊断 |
| `describe()` | 返回独立的能力描述：名称、说明、来源 schema、Setter schema、字段、计数单位及插件归属；修改返回值不改变注册表 |
| `validate(source)` | 验证 Collector 存在、来源选项、Setter 及其能力边界；无网络、无原始来源采集 |
| `collect(source, context)` | 根据已展开的有效来源配置执行一次采集，返回确定状态及其计数；不自行执行 `stop/skip` 策略 |

配置保存时的无效字段、未知 Collector 或不支持的 Setter 抛出 `LogAgentError`，`details` 包含例如 `sources[0].setters.group_by` 的字段路径。交互层负责映射为 422。运行时插件已经不可用则返回 `missing`；已经通过保存验证不代表实际来源必然在线。

`SourceConfig.template` 的展开由配置模块完成。同名 Setter 的实例值覆盖模板值，显式空列表也属于覆盖；模板的 `collector` 必须与实例一致。Manager 验证最终 Setter，不自行重新读取最新版模板。

### 4.3 CollectionResult 状态

| `status` | 条件 | `count/selected_count` 和内容 | Workflow 对应策略 |
| --- | --- | --- | --- |
| `success` | 有可用于拼接的处理后文本 | 原始、处理后计数分别保留；`items/text` 有效 | 接入共享输入 |
| `empty` | 本次来源范围内没有原始记录 | 均为 0，`items=[]`、`text=""`、`error=null` | `on_empty` |
| `filtered_empty` | 原始记录存在，Setter 或内容投影后没有可用条目 | 保留原始计数；`selected_count=0`，无内容 | `on_filtered_empty` |
| `missing` | 插件或指定文件不存在，或历史引用的必要内容未保存/已过期 | 无可用内容；`error` 说明缺失对象及原因 | `on_missing` |
| `failed` | 来源异常、权限错误、存档损坏、格式不符合契约或超限策略要求报错 | 无成功内容；`error` 保留错误码及可修正说明 | `on_error` |
| `timeout` | 本来源整体时限耗尽 | 不将未完成数据当成成功结果；记录时限 | `on_error` |

除正常空结果外，失败不能以 `items=[]` 隐藏原因。若原始数据已完整获得而 Setter/格式化失败，允许保留已知原始计数用于诊断，但 `items/text` 不作为可消费结果。`error` 使用公共错误结构，不输出秘密、完整堆栈或不受限的原始日志。

`success` 的文本不得仅含空白。原始空字典、选择字段后变成空字典的记录，及格式化后无内容的记录不计入 `selected_count`。分组只是表示方式，不能将组数写成条目数。

## 5. 插件发现与原子注册

启动扫描位置为 `<plugin_dir>/Collectors/*.py`，目录名称大小写与根契约一致；按文件名排序以便诊断及注册顺序可重现。模块名使用插件文件路径派生的私有名称，不与同名已安装包混淆。

插件导出 `register(registry)`，可以在同一次调用中注册多个 Collector。`registry.plugin_config` 是本文件同名 JSON 的独立配置副本，例如 `Collectors/custom.py` 对应 `Collectors/custom.json`。发现模块负责读取同名 JSON 并隔离错误；`discover(path, plugin_config)` 的参数可提供按文件名分组的显式配置覆盖。未提供的可选配置为 `{}`，必填设置仍需由插件校验。不得改成 `register(registry, config)` 而破坏统一入口。

每个文件的过程为：读取/取得插件配置 → 创建临时注册表 → 导入并检查 `register` → 执行声明 → 校验 schema、具体实现及名称冲突 → 一次性提交全部声明。冲突检查同时覆盖内置名称、已提交文件和本文件重复名称。

| 故障 | 结果 |
| --- | --- |
| 可选插件目录不存在或没有 `.py` 文件 | 内置来源仍然可用；产生可识别的目录诊断 |
| JSON 损坏、导入失败、缺少 `register`、声明无效 | 丢弃当前文件临时注册表；继续其他文件 |
| 文件先注册 `custom_a`，随后注册内置 `mock` | `custom_a` 与冲突声明都不进入正式注册表 |
| 不同文件注册同一个名称 | 先成功提交者保留；后一个文件整体拒绝 |
| 插件使用未知字段或声明无法执行的能力 | 拒绝该文件；不向 API 暴露半有效 schema |

这里的原子性限定为注册表可见性，不能回滚 Python 导入时任意外部副作用。插件规范要求导入与 `register()` 仅作声明，不启动线程、打开常驻连接或执行采集。首版启动时发现一次；替换插件文件需要重启服务，不引入热卸载语义。

## 6. Setter 与单来源处理

处理顺序固定为：保存来源范围内的原始计数 → 过滤 → 稳定排序 → 字段投影及移除无内容记录 → 分组和格式化 → 处理后计数。过滤先于字段投影，以便用户保留 `text` 的同时按未输出的字段筛选。分组和排序使用声明的原始字段值。

| Setter | 首版语义 |
| --- | --- |
| `fields` | 字段有序列表；未设置为插件默认字段，空列表为明确不保留字段；未声明字段拒绝 |
| `filters` | 按声明顺序组合，默认全部满足；每项指定 `field/op/value`，内置支持 `eq/ne/contains/in` 的适用类型 |
| `sort_by`、`descending` | 对声明字段稳定排序，相同键保持原始顺序；缺失值放在末尾 |
| `group_by` | 按声明字段分组，组的首次出现顺序稳定，组内保持前述顺序；计数仍为条目数 |

这些是可复用的实现助手，并不意味着每个插件自动支持全部 Setter。各 Collector 的 `setters_model` 与能力描述必须一致；插件未声明 `group_by` 时，即使保存模板包含它也返回校验错误。过滤只使用结构化操作，不解释 Python、shell 或任意表达式。

示例中的 `mock` 从配置提供的有限字典列表读取字段，声明其字段并返回独立副本：

```json
{
  "id": "mock_alerts",
  "collector": "mock",
  "options": {
    "items": [
      {"service": "api", "level": "warning", "text": "延迟升高"},
      {"service": "worker", "level": "info", "text": "批次完成"}
    ]
  },
  "setters": {
    "fields": ["service", "text"],
    "filters": [{"field": "level", "op": "eq", "value": "warning"}],
    "group_by": "service"
  },
  "timeout": 5,
  "on_error": "stop",
  "on_missing": "stop",
  "on_empty": "skip",
  "on_filtered_empty": "skip"
}
```

## 7. 历史记录 Collector

### 7.1 选择范围和记录边界

`history` 使用 Archive 的 `list/get/load_artifact/availability` 读取既有 session。只读取终态 session，不把当前正在执行的 session 加入自身输入；Workflow 已不存在也不妨碍读取仍在存档中的该 Workflow 历史。来源本身不重新调用历史 Workflow、原始 Collector 或 AI。

| `options` 字段 | 约束与含义 |
| --- | --- |
| `workflow_id` | 必填，指定历史所属 Workflow |
| `stages` | 非空有序列表，取 `collection/analysis/final`，默认 `["final"]`，不重复 |
| `last_n` | 可选正整数，限制最近 session 的次数，不是输出条目数 |
| `since`、`until` | 可选 UTC ISO 8601，时间范围为 `[since, until)`；二者同时存在时 `since < until` |
| `max_tokens` | 可选正整数，按下面的计数规则约束被选中的历史记录 |
| `token_counter` | 首版默认 `utf8_bytes`，显式描述预算单位；与 `max_tokens` 配合 |
| `overflow` | `truncate/error`；设置预算时必须明确，不能默默截断记录正文 |

选择次序为：Workflow 和终态过滤 → 时间范围 → 按 `(created_at, session_id)` 取最近 `last_n` 个 session → 展开指定阶段 → token 预算 → 交给 Setter。未指定 `last_n` 时使用时间范围内全部匹配 session；读取仍受来源总超时和有界文件操作约束，不无声套用固定的历史条数上限。

阶段展开以可独立解释的内容为完整记录：`collection` 的共享输入是一条，`analysis` 每个已保存分支结果是一条，`final` 每个已保存输出是一条。记录保留 `workflow_id/session_id/created_at/stage/output_id/text`；无输出标识的整体采集记录使用稳定的阶段标识。失败分支没有正文时只保留其已存档状态说明，不生成分析结论。

token 选择优先保留较新的完整记录，输出再按 session 时间升序及 `stages`/阶段内声明顺序排列。`CollectionResult.count` 是范围及预算选择后的记录数；`last_n` 则统计 session 数，两者不能混为一谈。

### 7.2 token 预算

`utf8_bytes` 对选中记录的确定文本表示计算 UTF-8 字节数，一字节占用一个预算单位，跨记录连接符也计入预算。它是本地可复现的保守内容预算，不宣称是所有模型的精确 token 数。首版无需下载模型词表；以后可注册具有明确版本与算法的计数器。

预算覆盖历史记录选择阶段的文本表示，不覆盖后续 Workflow 添加的来源计数、提示词或其他来源，也不把 `max_tokens` 宣称为整个模型请求的上下文上限。Setter 若改变展示格式，仍需在最终共享输入层另行判断模型容量。

`overflow=truncate` 按已定义的最近记录顺序逐条纳入，下一条放不下时停止，保留其余已选记录的完整边界。`overflow=error` 在候选历史超过预算时返回 `failed`，错误包含上限、实际计数和计数器名称。不得截取半条 JSON、半个分支结果或伪造摘要来适配预算。

第一条完整记录也放不下且策略为 `truncate` 时，范围内没有可选记录，返回 `empty`；本次预算决策写入关联诊断日志。Setter 排空已经选中的记录才返回 `filtered_empty`。

### 7.3 缺失与损坏

不存在匹配的历史 session 返回 `empty`。选中 session 明确关闭该阶段备份、备份已过期或阶段文件缺失时返回 `missing`，包含 session、阶段及 Archive 的原因；不假设它“没有历史”。文件校验失败、格式损坏或无法读取为 `failed`。若多个选中 session 中任一个必要记录不可用，整个来源报告该状态，不悄悄只返回其余部分；是否跳过此来源由 Workflow 决定。

```json
{
  "id": "recent_reports",
  "collector": "history",
  "options": {
    "workflow_id": "daily_report",
    "stages": ["final"],
    "last_n": 5,
    "since": "2026-09-01T00:00:00Z",
    "until": "2026-10-01T00:00:00Z",
    "max_tokens": 16000,
    "token_counter": "utf8_bytes",
    "overflow": "truncate"
  },
  "setters": {"fields": ["created_at", "text"]},
  "timeout": 15,
  "on_error": "stop",
  "on_missing": "stop",
  "on_empty": "skip",
  "on_filtered_empty": "skip"
}
```

## 8. 工具日志 Collector

`logs` 默认使用 `CollectionContext` 中的工具日志文件，只读取普通文件。`options.max_bytes` 与 `options.max_lines` 都是正整数；先读取最多指定字节的尾部，再保留最多指定完整行。默认值为 65536 字节和 200 行，可通过来源配置显式降低或提高。

定位字节边界时丢弃开头被切断的半行，正确处理跨边界 UTF-8 字符。为避免读到仍在写入的半行，忽略末尾尚未结束的行；空文件或没有完整行返回 `empty`。读取开始时固定文件大小上界，后续追加的内容交给下次采集。

每个记录包含尾部片段内的有序 `line` 和 `text`，不把片段内编号宣称为原文件绝对行号。可按文本内容过滤、按声明字段选择/排序/分组。文件不存在返回 `missing`；无权限、非普通文件或读取异常返回 `failed`。日志轮转后路径重建由下次采集自然读取，不保留跨采集失效的文件句柄。

```json
{
  "id": "recent_logs",
  "collector": "logs",
  "options": {"max_bytes": 65536, "max_lines": 200},
  "setters": {
    "fields": ["text"],
    "filters": [{"field": "text", "op": "contains", "value": "ERROR"}]
  },
  "timeout": 5,
  "on_error": "skip",
  "on_missing": "skip",
  "on_empty": "skip",
  "on_filtered_empty": "skip"
}
```

## 9. 并发、超时与生命周期

Workflow 的采集并发上限控制同时发起的来源调用，Manager 不再创建一套无界队列。不同来源可以并发执行，同一 Collector 的不同实例也不能共享本次结果或修改注册表。返回顺序由 Workflow 保持，完成时间不决定共享输入顺序。

`SourceConfig.timeout` 以秒计，是一次来源执行从实际开始到读取、Setter、格式化完成的整体预算；等待 Workflow 并发槽位不消耗该来源预算。设置必须大于零且为有限值。文件读取通过工作线程完成；不会在事件循环中读取整份历史文件或整份日志。

取消向 Collector 协程传播，不能被转换为 `empty` 或普通 `failed`。插件必须使用可取消等待并为自身网络操作设置超时；首版不承诺能强制终止一个违反接口要求、在协程中无限阻塞的插件。

`asyncio.to_thread` 的调用方被取消不会杀死底层线程。内置来源只做有限普通文件操作，跟踪尚未结束的读操作，结果在取消后不再注入 session；关闭时回收已启动任务。Collector 不要求单独的 `start/stop` 公共协议，也不维护常驻接收任务。导入和注册失败不能留下未跟踪的线程。

日志至少关联 session、Workflow、source、Collector、错误码、执行耗时及计数。正常空结果可以记录为诊断，不能被包装成 ERROR 来改变业务策略。

## 10. 可验收测试矩阵

| 场景 | 输入或故障注入 | 可验收结果 |
| --- | --- | --- |
| 内置发现 | 空插件目录 | `mock/history/logs` 均可描述和验证 |
| 多声明注册 | 一个文件声明两个合法名称 | 两项同时出现，schema 可查询 |
| 文件原子性 | 先合法注册，再抛错或重复注册 | 该文件零新增；其他文件可用 |
| 无效声明 | 导入失败、损坏 JSON、缺少入口、未知 Setter | 明确诊断；不启动半配置来源 |
| 模板复用 | 同一 Collector 模板加实例覆盖 | 使用展开后值；不同 Collector 模板拒绝 |
| 成功与计数 | 3 条原始记录，过滤保留 2 条再分组 | `count=3`、`selected_count=2`，组数不改变计数 |
| 空状态 | `[]`、非空但全被过滤、来源抛错分别运行 | 依次为 `empty/filtered_empty/failed` |
| 字段边界 | 空字段列表、未知字段、全部投影为空 | 合法空投影为 `filtered_empty`；未知字段拒绝 |
| 稳定顺序 | 相同排序键、多组且来源返回确定顺序 | 多次执行文本和顺序一致 |
| 历史次数/时间 | 多 session、多输出及边界时刻 | `last_n` 按 session；时间左闭右开；输出次序确定 |
| 历史 token | 多字节中文、分隔符、恰好到边界、首条超限 | UTF-8 计数可复算；仅截整条；`error` 明确报错 |
| 历史空/缺失/损坏 | 无 session、备份关闭/过期、摘要不符 | 分别 `empty/missing/failed`，原因可区分 |
| 无重复采集 | 对原始 Collector/Workflow/AI 设置调用哨兵 | 历史读取时调用次数均为 0 |
| 日志有界读取 | 大文件、UTF-8 跨块、末尾半行、文件轮转 | 读取字节和完整行受限，不扫描整份文件 |
| 超时与并发 | 一个慢 Collector 与一个立即返回 Collector | 前者 `timeout`；后者完成；共享缓存不串数据 |
| 取消与关闭 | 在异步等待/线程读取期间取消 | 取消传播；无后续结果注入；无未跟踪后台任务 |

测试使用临时插件、临时文件、模拟 Archive 和可控协程，不访问真实外部源。跨来源共享输入、策略执行及 session 恢复由 Workflow 集成测试进一步验收。

## 11. 后续扩展位置

后续健康监测复用 Collector 的类型发现与可选能力描述，不把健康轮询混入 `collect()`。YAML Toolset 可将一次来源调用适配为 AI 工具，仍由 Collector 验证 Setter 和来源 schema；适配层负责工具授权与参数映射。Workflow 分支来源子集只改变 Workflow 选用哪些 `CollectionResult`，无需改变本模块结果结构。

更精确的 token 计数器可通过扩展注册，但配置及存档需固定算法标识和版本，避免恢复时同一个预算得到不同历史范围。首版不要求图片输入、插件热替换、常驻采集服务或任意 shell 执行能力。
