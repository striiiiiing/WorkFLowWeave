# 实施计划

1. 完成严格数据模型、轻量 JSON Schema 校验和配置资源管理。
2. 完成 QwenPaw 风格的 manifest/backend/plugin.register 注册流程；mock 作为普通 Collector 插件加载。
3. 完成无状态的 Collection、AI、Channel 和 Workflow 单次调用链路。
4. 使用 Python 标准库 `logging` 负责诊断输出；logs Collector 只做有界读取。
5. API、CLI 和生命周期只装配上述能力，不保存执行期间的状态、阶段结果或恢复材料。
