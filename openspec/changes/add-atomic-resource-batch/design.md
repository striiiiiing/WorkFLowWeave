# 设计

`save_many(resources)` 接收按 `ResourceKind` 分类的资源列表。在 `ResourceStore` 已有锁内构造一份候选视图，逐项按现有模型校验，收集变更键，然后复用 `_commit` 的全量引用校验与 `_publish` 的原子文件替换。任何校验或发布失败都不替换内存视图；空批次不写盘。

`LifecycleResourceStore` 在父类成功返回且批次非空时只调用一次 `_published`。沿用现有 `save` 的 upsert 语义；不增加批次级模式参数，保持与远端参考实现一致。资源内部同一 ID 重复时按输入顺序以后项为准；调用者应提交唯一 ID，当前需求不增加单独的冲突策略。

本变更只增加 Python 资源存储接口，不扩展 HTTP 协议。依据现有 `ResourceStore._commit` 已承担完整候选校验和发布、远端同名实现也仅提供存储接口。
