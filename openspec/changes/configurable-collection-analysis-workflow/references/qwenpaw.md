# QwenPaw 参考记录

本次依据 [agentscope-ai/QwenPaw](https://github.com/agentscope-ai/QwenPaw) 提交 `983b3cebf4dda409458783b286d3a95cc80d135f` 阅读相关源码。引用固定提交，避免后续主分支变化影响复查。

| 源码 | 已核实内容 | 本项目取舍 |
| --- | --- | --- |
| [plugins/architecture.py](https://github.com/agentscope-ai/QwenPaw/blob/983b3cebf4dda409458783b286d3a95cc80d135f/src/qwenpaw/plugins/architecture.py) | PluginType 包含 channel，PluginManifest 描述入口及类型。 | 仅定义 collector/channel 两种类型，省去前端、工具、Hook 等运行时体系。 |
| [plugins/loader.py](https://github.com/agentscope-ai/QwenPaw/blob/983b3cebf4dda409458783b286d3a95cc80d135f/src/qwenpaw/plugins/loader.py#L272) | 扫描插件目录的子目录，读取 plugin.json、解析 manifest，单项失败记录诊断；清理按 owner 执行。 | 采用目录 `plugin.json` + `entry.backend` 入口模型，单文件不作为插件格式。 |
| [入口对象与调用](https://github.com/agentscope-ai/QwenPaw/blob/983b3cebf4dda409458783b286d3a95cc80d135f/src/qwenpaw/plugins/loader.py#L575) | 从导入模块获取 plugin 对象并调用 register(api)，也支持等待异步注册。 | 本项目入口导出 plugin 对象；首版 register 为同步声明过程，采集和发送仍为异步执行。 |
| [plugins/api.py](https://github.com/agentscope-ai/QwenPaw/blob/983b3cebf4dda409458783b286d3a95cc80d135f/src/qwenpaw/plugins/api.py#L679) | PluginApi.register_channel 作为插件注册入口。 | 使用窄注册 API，绑定类型与配置声明，平台行为不进入 Workflow。 |
| [plugins/registry.py](https://github.com/agentscope-ai/QwenPaw/blob/983b3cebf4dda409458783b286d3a95cc80d135f/src/qwenpaw/plugins/registry.py#L765) | key、实现类型、config_fields 校验；拒绝覆盖内置 key/已有 key；按 plugin_id 清理渠道注册。 | 采用 owner 与冲突检查，配置统一使用 JSON Schema，不要求继承其 BaseChannel。 |
| [app/channels/registry.py](https://github.com/agentscope-ai/QwenPaw/blob/983b3cebf4dda409458783b286d3a95cc80d135f/src/qwenpaw/app/channels/registry.py) | 合并内置与插件 Channel，可选渠道依赖错误独立处理。 | 内置与扩展使用统一能力查询，失败明确对外报告；不复制平台清单。 |

QwenPaw 的渠道注销只移除注册项，实例由后续配置 reload 清理；本项目在无活动运行的插件 reload 边界统一处理清理。本项目沿用其目录 manifest 与 backend 入口思路，但仅暴露收窄的 `CollectorPluginApi`、`ChannelPluginApi`；配置模块调用 `plugin.register(api)` 后发布 `collectorRegister` 和 `channelRegister`。其配置字段机制是 UI 字段描述，本项目的 JSON Schema、快照绑定和单条发送是本地设计选择，不宣称兼容 QwenPaw 的完整插件格式。

通知只采用 `async send(config, notification)` 调用：不引入消息队列、优先级或对话路由。首版邮件与 Mock 文件渠道按本项目需求定义，并非声称这些是 QwenPaw 的对应内置实现。

分析采用旁边的无 checkout、浅克隆参考目录，仅按需读取上述五个源码文件；未安装依赖或下载平台资源。参考副本不进入当前项目 Git 内容。
