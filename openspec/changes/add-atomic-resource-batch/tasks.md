# 任务

依据：[任务要求](../backendFix/任务要求.md)、[设计](design.md)、[行为规范](specs/resource-storage/spec.md)。

- [x] 1.1 ResourceStore 增加 `save_many`，复用现有校验、锁和原子发布；测试跨资源引用的成功与失败原子性。
- [x] 1.2 生命周期层在非空成功批次后刷新一次；测试失败不刷新。
- [x] 1.3 运行定向测试、静态检查与 OpenSpec 校验，记录结果。

默认值依据：`save_many` 采用现有 `save` 的 upsert 语义，避免引入另一套保存模式；空批次没有变更，因此不发布也不刷新。远端 `workflowServer` 的 `ResourceStore.save_many` 与 `LifecycleResourceStore.save_many` 采用相同边界。

验证：`tests/config/test_resource_store.py` 25 项通过；改动文件 Ruff 检查通过；`openspec validate add-atomic-resource-batch --strict --no-interactive` 通过。
