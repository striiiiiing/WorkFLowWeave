# 插件实现目录迁移

## 决策依据

- 用户要求：将作为插件的具体实现移入插件目录，包含通知渠道和 Collector。
- [配置设计](../../modules/config/design.md)：PluginRegistry 是唯一发现入口，
  按 plugin.json 与 plugin.register(api) 发布能力；Manager 不自行扫描或导入。
- [渠道设计](../../modules/channel/design.md)：Channel 以插件形式导入并注入 Manager。
- [采集设计](../../modules/collection/design.md)：来源专属处理归 Collector 实现；
  mock/logs/history 的既有 schema 与行为沿用。
- [最新渠道设计](../../../../redesign-agent-channel-manager/design.md)：Web 由应用装配，
  QQ/Test 是实现传输与消费契约的适配器。
- 当前 `src/workflowweave/lifecycle/defaults.py` 只创建文件通知渠道、不创建旧采集来源；
  本次目录迁移不恢复旧默认源或修改 MCP/CLI 契约。

## 范围与结构

这是结构修复：移除核心中的具体适配器和默认 Collector 自动注册，而非
在插件目录增加回指核心的包装。proposal.md 和 design.md 不修改。

| 插件目录 / owner | 能力 |
| --- | --- |
| plugins/mock | collector:mock |
| plugins/logs | collector:logs |
| plugins/history | collector:history |
| plugins/mock_file | channel:mock |
| plugins/email | channel:email |
| plugins/qq | channel:qq |
| plugins/test_channel | channel:test |

文件渠道 owner 使用 mock_file，使其能与 collector:mock 独立重载；
能力 name 保持 mock，避免修改已有 ChannelConfig。
Web、Manager、协议、队列和应用内部 Agent 工具保留在核心。
注册器默认注入空 Collector 元组，因为目录是适配器可用性的唯一来源；
保留显式能力注入参数供 Web 装配及隔离测试使用。
根插件 enabled 默认值沿用现有 PluginSettings，不新增默认值或回退。

## 任务

- [x] 迁移七个具体实现，并为每个插件提供清单及同步注册入口。
- [x] 删除核心适配器导出和自动补注册，更新应用装配入口。
- [x] 更新测试导入，应用集成测试显式安装目录插件。
- [x] 更新浏览器测试后端 plugin_dir，增加目录及部署说明。
- [x] 验证发现、真实 owner、禁用不导入、定向重载和实际应用启动。
- [x] 执行适配器回归、静态检查、构建及差异复查。

## 验证结果

- 适配器回归：迁移前后均为 158 passed，覆盖 mock/logs/history、
  邮件、QQ 和文件通知。
- 配置、Agent 注册视图、默认资源及 Provider 集成：117 passed，
  包含三个新增的插件目录、禁用与定向重载测试。
- 生命周期回归：37 passed，包含真实 Test 渠道入站、回复、插件重载和清理。
- 通用渠道与既有 Workflow/来源回归：78 passed。上述后端测试分组执行，
  每个进程均由 timeout 60s 设置硬上限，共 390 passed。
- 全仓测试收集：1008 tests collected；未执行全量回归。
- Ruff 全仓 src/tests/plugins 和两个浏览器测试后端通过；git diff --check 通过。
- uv build --wheel 成功。完整 sdist 构建因扫描大型工作区而主动停止，
  本次只验证受影响后端包的 wheel。
- 启动隔离的真实浏览器测试后端，通过 HTTP 验证 health=ready、
  13 项插件能力、正确 owner、默认文件通知渠道和插件 reload，均 HTTP 200；
  reload 后仍 ready，临时服务已关闭。
- 七个搬迁实现均与原文件逐字相同；未新增核心回指、重复实现或静默回退。
