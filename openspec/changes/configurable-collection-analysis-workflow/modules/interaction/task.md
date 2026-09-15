# Interaction 任务

- 提供配置、插件能力和单次 Workflow 执行入口。
- 提供 session 列表、单个 session/阶段结果和历史查询，并允许调用 `WorkflowService.recover/resume` 恢复未完成运行。
- API 与 CLI 复用同一应用服务和错误映射，不访问模块私有文件。
