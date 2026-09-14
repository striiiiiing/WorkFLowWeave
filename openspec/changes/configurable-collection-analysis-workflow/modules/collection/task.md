# Collection 任务

1. 实现 CollectorManager 的注册视图消费、配置校验、超时、取消和统一结果映射。
2. 通过插件 manifest 注册 mock Collector；collection 包只保留 logs 等通用实现，不主动注册 mock。
3. 使用 Python 标准库 `logging` 作为诊断日志设施；logs Collector 只负责有界读取既有 logging 输出。
4. 覆盖插件注册、Setter、空状态、错误脱敏、并发和取消测试。
