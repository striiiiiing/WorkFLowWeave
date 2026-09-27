# 插件作者：提供可读结果

现有采集插件不用修改：前端会显示 `status`、`count`、`text` 和错误。若需要更适合用户阅读的版式，可在 `CollectorOutput` 返回可选 `report`：

```python
return CollectorOutput(
    status="success", count=2, text="提供给 AI 的原始内容",
    report={"sections": [
        {"kind": "text", "title": "本次概况", "text": "发现 **2** 条告警。"},
        {"kind": "metrics", "title": "关键数字", "items": [
            {"label": "告警数量", "value": 2, "unit": "条"}
        ]},
        {"kind": "table", "title": "告警明细", "columns": ["类别", "数量"],
         "rows": [["网络", 1], ["磁盘", 1]]}
    ]}
)
```

段落支持 Markdown，HTML 会按文字显示。指标值为文字或有限数值；表格单元格为文字、有限数值、布尔或空值，每行必须与列标题数量一致。不要返回 HTML、脚本或需要浏览器执行的代码。

报告只改变展示。`text` 仍是传给分析步骤的输入，`status/count/error` 仍决定流程行为。前端优先显示自定义报告，并提供“查看提供给分析的正文”展开项；高级模式可以查看完整 JSON。声明无效会产生 `invalid_collector_output`，不会悄悄丢弃。报告随本次结果存档，所以后续插件更新不会改写历史展示。

## 为资源提供默认编号前缀

采集器或渠道能力对象可声明可选的 `id_prefix` 属性。例如：

```python
class MyCollector:
    name = "my_collector"
    id_prefix = "my_source"
    # 其余采集器接口照常实现。
```

选择该能力时，新资源编号会自动生成为 `my_source_<UUID>`。省略属性或设为 `None` 时，只生成 UUID；旧插件不需要修改。作者声明的前缀必须为 1–43 位英文字母、数字、下划线或短横线，元信息输出时使用 `CapabilityDescription` 验证；43 位给下划线和 36 位 UUID 留出空间，使编号不超过既有的 80 位限制。

这只是默认建议。用户可以在普通界面的“资源编号”中改写或删除前缀；用户编号只受原有字符及长度规则约束，不要求匹配插件前缀。切换能力不会覆盖用户已经手工填写的编号。
