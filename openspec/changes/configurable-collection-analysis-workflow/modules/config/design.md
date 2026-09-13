# 配置与资源管理模块设计

[总设计](../../design.md) · [数据模型](../../contracts/data-models.md#2-配置资源) · [接口契约](../../contracts/module-interfaces.md#2-配置与资源管理)

配置模块保存可复用资源、负责插件发现与注册、维护引用关系，并为每次运行提供独立 WorkflowSnapshot。插件专属语义校验由 Collector/AI/Channel 完成；本模块不执行采集、模型或通知。

## 配置分层与识别

| 层级 | 首版 JSON 入口 | 生效时机 |
| --- | --- | --- |
| 系统 | CLI 显式指定的系统配置文件 | 启动时固定 data_dir、plugin_dir、监听和全局上限；修改后重启。 |
| 插件设置 | plugin_dir/config.json，使用 PluginConfiguration | 启动/插件 reload 控制启用及 options 默认值。 |
| 插件能力 | 每个插件目录的 plugin.json + entry.backend 指定的入口 .py | 配置模块读取 manifest、导入入口并发布 collectorRegister/channelRegister，不保存用户凭据。 |
| 资源 | data_dir/resources.json | CRUD 或资源 reload 发布新版本，包含 sources/setters/ai/channels/workflows 五个集合。 |
| 运行 | WorkflowSnapshot | trigger 时复制有效资源；当前及恢复运行一直使用该副本。 |

以上文件布局是首版实现选择，不是公共 API 的路径承诺。启动显式缺失的系统文件报错；首次空数据目录可建立五个空资源集合，已存在但损坏的文件报错。插件配置文件不存在等于无覆盖。QwenPaw 的类型、注册与配置描述思路见 [参考记录](../../references/qwenpaw.md)。

系统相对路径按系统配置所在目录解析；插件 manifest 入口按插件包目录解析。来源/渠道 options 内路径由能力 schema 的说明及所属模块解释，快照固定有效位置，不能把所有名叫 path 的字段统一重写。

## 插件发现与注册

配置模块采用 QwenPaw 风格的“目录 manifest + 后端入口”模型。它扫描 `plugin_dir` 下的直接子目录，每个插件目录必须包含 `plugin.json`；manifest 的 `entry.backend` 指向目录内的相对 `.py` 文件。入口模块只作为可信 Python 扩展导入，不执行 shell 字符串，不提供沙箱。

```text
plugins/
  config.json
  my_source/
    plugin.json       # kind=collector, entry.backend="main.py"
    main.py           # 导出 plugin，plugin.register(api) 注册能力
  my_channel/
    plugin.json       # kind=channel, entry.backend="channel.py"
    channel.py        # 导出 plugin，plugin.register(api) 注册能力
```

发现顺序为内置能力、外部插件目录稳定排序。配置模块读取并校验 `id`、`version`、`kind`、`api_version`、`entry.backend`，检查入口路径不能越出插件目录；禁用插件不导入入口。按 QwenPaw 的入口约定，导入后读取模块导出的 `plugin` 对象并调用 `plugin.register(api)`；`api` 按 manifest.kind 只暴露 `register_collector` 或 `register_channel`。一个入口可以注册多个同类能力，不能跨 kind 注册。

注册 API 把声明先放入当前插件的临时集合。配置模块验证能力名、JSON Schema、实现/工厂、内置名称冲突、已有名称冲突及插件 defaults；全部通过后一次性发布并记录 owner。任一声明失败则撤销该插件本轮全部注册并记录 DiscoveryReport，其他插件继续加载。插件 reload 按 owner 清理旧声明，再重复同一流程；已保存资源保留，缺失能力留给运行阶段按策略处理。

例如 `my_source/plugin.json`：

```json
{
  "id": "my_source",
  "version": "0.1.0",
  "kind": "collector",
  "api_version": 1,
  "entry": {"backend": "main.py"}
}
```

注册入口及 `CollectorPluginApi` / `ChannelPluginApi` 以[接口契约 §9](../../contracts/module-interfaces.md#9-插件注册入口)为准；两个注册结果的 `get(name)` 与 `describe()` 查询能力以[接口契约 §2](../../contracts/module-interfaces.md#2-配置与资源管理)为准。

配置模块对外发布只读注册视图：`collectorRegister: CollectorRegister` 提供给数据采集模块，`channelRegister: ChannelRegister` 提供给 Channel 网关。这里的名称表示注册结果，不要求业务模块再次调用插件入口；插件入口只在配置模块发现或 reload 时调用。

## 内部组织

`ConfigurationReader` 读取系统、插件设置和 manifest；`PluginRegistry` 负责导入入口、接收注册、校验声明并发布 `collectorRegister`/`channelRegister`；`ResourceStore` 作为应用入口提供 CRUD、resolve、snapshot 和 reload_resources；内部仓库负责 JSON 持久化。`CredentialManager` 提供保护与解析能力，`SnapshotResolver` 可以是 ResourceStore 内部函数，无需另一份数据缓存。

ResourceStore 接收注入的业务校验函数。WorkflowService 负责定义语义，使用同一提交入口；校验函数不能反向调用 save，避免循环提交。`PluginRegistry` 的 schema 是插件字段唯一来源，交互端通过 CapabilityDescription 查询；数据采集模块和 Channel 网关只接收注册结果，不自行读取 plugin_dir 或导入入口。

## 默认值与配置合并

插件设置仅含 enabled 和按能力名组织的 options defaults，不引入插件私有运行时配置对象。默认值必须在已注册 options_schema 中声明；声明之外的默认字段直接报错。

保存来源/渠道实例时，依次应用能力 schema 默认值、插件 defaults、实例显式 options，同名键整体覆盖，不深度混合；再验证完整结果，规范化为持久化 options。修改插件 defaults 影响后续保存/导入，已保存实例保留原有效值，执行时不再与可变 defaults 合并。

Setter 使用“模板 → 实例显式键”的独立规则，不与 options 混合；展开后的 Setter 再过 Collector 校验。显式空列表仍是覆盖。AIConfig 直接保存 provider 支持的模型选项，遵循 AI 模块契约。

## 原子提交与快照

首版资源规模小，五个集合存于一份版本化 JSON 封套，内存持有一份有效视图；写入过程在单进程资源锁内串行执行：

1. 从当前视图生成候选副本，检查 kind/ID、create/replace/upsert 的存在性要求及严格字段结构。
2. 完成资源所属模块语义校验和受影响 Workflow/Setter 引用校验；失败保留旧视图，不调用外部付费能力。
3. 将完整候选内容写入同目录临时文件并原子替换，成功后发布内存视图；文件失败不报告保存成功。

删除被引用资源返回冲突，不级联删除。snapshot 从同一已发布视图深复制 Workflow 及恰好覆盖引用的资源，展开 Setter、固定路径、保留 Credential 引用/密文。生成 snapshot 不重新验证 Collector 当前在线或已加载，缺失插件留给采集阶段处理。

resolve 供尚未保存的定义做关系校验，不写资源。对外 get/list 返回独立副本，调用者不能修改仓库状态。资源 reload 采用同一候选校验/发布过程；离线编辑资源文件与 API 并发写入不在多写入者一致性保证内。

## 凭据

来源 options、渠道 options 和 AIConfig 中的秘密只保存 Credential，运行时按需解析；不能把明文放入 defaults 或任意扩展字段绕过约定。插件 schema 明确哪些字段为 Credential。返回配置、日志、错误、快照都不包含解密值。

主密钥读取、首次生成、已有密文恢复和格式错误规则以数据模型 §2.5 为准。快照固定引用/密文，不备份明文；缺少原环境变量或主密钥时显式失败，不使用最新资源中的凭据替换。

## 验证要点

检查目录 manifest 与入口对象、禁用插件不导入、一个插件多能力、重复 ID/能力名、kind 不符、默认配置无效、单插件失败无残留及注册结果只读；同时检查 defaults 的覆盖与固化、Setter 归属、未知字段、删除引用资源、提交中断保留旧视图、并发写入和 snapshot 一致性，以及更新资源后旧 session 地址/提示词不改变。
