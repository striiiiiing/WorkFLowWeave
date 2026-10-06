# ZON 输入序列化精确性修复

## 问题

对结构化工作流输入使用 `zon-format` 的默认 `zon.encode` 时，字典压缩解码器会裁剪带引号字符串的尾随空白。这样序列化后再解码得到的值与原 JSON 值不同，破坏了输入格式的精确性校验。

## 修改方案

在 `src/workflowweave/workflow/input_formats.py` 的 `zon` 分支改用 `ZonEncoder(enable_dict_compression=False)`，保留 ZON 的表格/增量编码，同时关闭会改变字符串值的字典压缩。现有统一的深度 JSON 比较仍负责拒绝任何不能完整往返的值。

## 依据与验证

该修改围绕序列化函数的现有往返不变量，避免在调用方增加补丁或放宽比较。`tests/test_evaluation.py` 与输入处理测试覆盖 ZON 往返；后端测试子代理会在逐模块回归中复验。
