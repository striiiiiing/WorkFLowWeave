# aggregate 成功推送补充任务

## 依据与决定

用户明确要求“aggregate 成功也要发送一次”。依据 [design 第 4 节](../../design.md) 与 [流式规范](../../specs/workflow-stream-execution/spec.md)，在此前选择性推送基础上增加 aggregate 成功，保留旧任务历史。

- aggregate 完成必要业务提交并冻结输出后推送，不等待 notify；未启用模型 fan-in 时也必须推送。
- fan-in 和 aggregate 为不同业务完成点时分别推送。同一结果被重复分类或由父子图重复暴露时只更新一次，并保留 aggregate 成功含义。
- 沿用已有稳定业务身份、异步消费和提交边界，无新增延迟、并发或保留期默认值。

## 任务

- [x] 1.1 最小同步 proposal、design 和流式规范，补充 aggregate 推送及验收场景。
- [x] 1.2 严格校验 OpenSpec 并检查文档链接、空白及修改范围。
- [ ] 2.1 将 aggregate 成功纳入必要业务更新映射，关闭模型 fan-in 时仍发布完成状态。
- [ ] 2.2 验证 aggregate 推送不等待 notify，两个独立完成点不互相吞事件，同一结果重复暴露不重复条目。

## 验证记录

本轮仅修改文档，运行代码与推送测试尚未实施。

OpenSpec 严格校验通过（退出码 0）；相对链接、围栏及逐文件空白检查通过；已审查本次推送点与场景描述的一致性。
