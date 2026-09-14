# 模块接口契约

所有接口只服务单次调用；除可复用配置资源外，系统不保存执行状态、阶段正文、历史或恢复材料。

## 配置与插件

`PluginRegistry.discover_plugins(config)` 扫描 `plugin_dir` 下的 manifest，导入 `entry.backend`，调用同步的 `plugin.register(api)`，并发布只读 `collectorRegister` 与 `channelRegister`。CollectorManager 和 ChannelManager 只消费对应注册视图。`reload_plugins` 按 owner 清理并替换选定插件的声明，其他 owner 保持不变。

`ResourceStore` 提供资源的 `save/get/list/delete/resolve/snapshot`；`snapshot` 返回本次执行使用的独立 `WorkflowSnapshot`，不创建运行记录。

## Collection

```python
class CollectorManager:
    def describe(self) -> list[CapabilityDescription]: ...
    def validate(self, source: SourceConfig) -> None: ...
    async def collect(self, source: SourceConfig, context: CollectionContext) -> CollectionResult: ...
```

Collector 由插件注册 `name`、JSON Schema、字段和 `collect` 协程。`validate` 无 I/O；`collect` 只处理当前输入，返回统一的成功、空、缺失、失败或超时结果。

## AI 与 Channel

AI 接收明确的 AIConfig、prompt 和 input，返回本次调用的 `AnalysisResult`。Channel 消费注册视图，按给定快照配置执行一次 `send`，返回 `DeliveryResult`；网关不排队、不缓存、不重试、不读取历史。

## Workflow

Workflow 在一次 `trigger` 调用内完成 `collect -> analyze -> aggregate -> notify`，阶段结果以内存对象传递。`WorkflowSnapshot` 固定本次调用配置；调用结束、进程重启或配置变更后不提供 `wait/resume` 的持久化语义。取消只影响当前调用。

## 交互与生命周期

API/CLI 调用上述服务并映射统一 `ErrorResponse`。生命周期只负责装配、插件 reload、准入和资源释放，不初始化任何运行状态存储。
