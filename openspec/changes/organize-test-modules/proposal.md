## Why

测试文件集中在根目录、缺少逻辑说明，并存在测试文件之间的辅助对象导入，增加定位和维护成本。用户要求每个测试模块描述逻辑，模块专属测试放入 `tests/<模块名>`，其他测试保留在外层。

## What Changes

- 按被测职责整理后端测试目录，保留共享契约与跨模块集成测试在根目录。
- 为后端、前端测试文件及辅助模块补充中文逻辑与依赖说明。
- 共享辅助对象使用明确的测试包导入，不依赖测试发现顺序。
- 提供测试目录导航、运行入口及执行验证记录。

## Capabilities

### New Capabilities

无。本次是测试维护整理，`.openspec.yaml` 声明 `skip_specs: true`。

### Modified Capabilities

无。不改变产品行为、接口或既有设计决策。

## Impact

影响 `tests/`、`frontend/tests/` 和本 change 文档；模块测试的旧路径需改用新路径。生产代码、依赖与既有 OpenSpec proposal/design 不变。
