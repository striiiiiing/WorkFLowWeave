# 装配与生命周期设计

[总设计](../../design.md) · [插件模型](../../contracts/data-models.md#6-能力描述和上下文) · [QwenPaw 依据](../../references/qwenpaw.md)

装配层是依赖组合入口，负责服务启停与依赖注入。插件读取、入口导入、注册和 owner 清理由配置模块承担；装配层只取得 `collectorRegister` 与 `channelRegister` 并分别注入数据采集模块和 Channel 网关。

## 启动顺序

1. 读取 SystemConfig，初始化配置存储和凭据。
2. 打开 LangGraph SQLite checkpointer，建立 Workflow 的 SessionView 查询能力；存储不可用时不开放运行准入。
3. 创建配置模块及其 PluginRegistry，发现并注册 history、logs、mock 等 Collector 插件及 Channel 插件，发布 `collectorRegister` 与 `channelRegister`。
4. 将两个注册结果分别注入数据采集模块与 Channel 网关，为历史 Collector 注入 SessionView 只读接口，再解析五类资源及引用。已保存来源的插件缺失保留为诊断，执行时按 on_missing 处理。
5. 装配 AIService、ChannelManager、WorkflowService 和 API；由 Workflow 检查 checkpoint，将遗留 created/running session 标记 interrupted 后开放准入及定时触发，不自动恢复运行。

所有依赖由构造参数注入。健康检查汇总已知本地状态，不通过启动流程发送探测邮件、读取实际来源或调用付费模型。Channel 实例按快照配置首次使用时初始化并常驻，服务关闭时统一释放；服务启动不遍历所有目标建立远端连接。

## 插件注册协调

插件目录格式、`plugin.json`、`entry.backend`、`plugin.register(api)` 入口及 `collectorRegister`/`channelRegister` 发布规则由[配置模块](../config/design.md#插件发现与注册)定义。装配层不扫描插件目录，也不保留第二份 manifest、schema、owner 或能力注册表。

配置模块完成一次发现后输出两个只读注册结果：`collectorRegister` 注入 CollectorManager，`channelRegister` 注入 ChannelManager。类型、schema、实现/工厂在每一注册结果内保持同一条记录，业务模块的 `describe` 和 `validate` 直接从注入结果投影。加载时不调用 collect/send，不启动永久接收循环；单插件导入/注册异常由配置模块隔离并写入 DiscoveryReport。

## reload

`POST /api/reload?scope={scope}` 提供显式入口，scope 为 resources 或 plugins，默认 resources。没有后台文件 watcher。

resources：重新读取资源 JSON，完整验证后原子替换有效视图；失败保留上一版。当前调用已经取得的快照不变；成功后按新 Workflow 定义重建未来定时计划。系统路径、监听及全局上限仍通过重启生效。

plugins：仅在没有活动运行时允许，原子关闭准入并暂停定时触发后再检查活动数；存在活动运行返回冲突，不自动取消它们。调用配置模块按 owner 清理旧声明、读取 `plugin.json` 并重新导入入口，再把新发布的 `collectorRegister`/`channelRegister` 注入两个业务模块；装配层不复制或重建注册内容。失败插件保持不可用并报告诊断，其他有效插件可以使服务 degraded 后继续接收运行；不宣称任意 Python 导入副作用可回滚。

插件 reload 在没有活动运行的边界，先关闭受影响 owner 的渠道实例，再由配置模块清理旧注册并加载新代码。卸载是 reload 后 owner 不再存在的结果，移除其全部类型/schema/工厂；已保存资源由配置模块按引用规则处理。

## 关闭与清理

关闭先禁止新准入和定时触发，再由 RunCoordinator 等待或取消活动 session 并完成状态写入；随后关闭模型客户端、渠道常驻实例和插件资源，最后关闭 SQLite checkpointer。ChannelManager 等待当前 send 的有界清理后统一 stop。启动失败也按已获取资源清单逆序释放。

stop/shutdown 可重复调用，清理错误独立记录，不掩盖原始启动或业务失败。阻塞 SDK/线程必须有实际 I/O 时限；取消 async 包装并不强制终止线程。首版不运行无所属的后台任务。

## 验证要点

覆盖配置模块提供的目录插件注册结果注入、一个插件多能力、重复 ID/key、manifest 与 kind 不符、`entry.backend` 路径越界、入口导入失败、默认配置无效、注册原子性、插件 reload 活动冲突、卸载无残留和失败启动清理。验证 checkpointer 不可用时不开放准入、遗留 session 标记中断，以及渠道实例和数据库按序释放。
