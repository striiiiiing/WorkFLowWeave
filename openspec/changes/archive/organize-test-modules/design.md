## Context

依据用户的目录与说明要求，以及 [OpenSpec 存放约定](../../README.md)。已有 [总设计](../configurable-collection-analysis-workflow/design.md) 与 `modules/*/design.md` 的业务模块边界不变。

## Goals / Non-Goals

目标：测试位置反映职责，每个文件可从顶部说明了解覆盖逻辑、验证方式与依赖；迁移不丢失用例、不改变断言行为。
不在本次范围：产品设计变更、拆分所有大型测试函数、新增业务覆盖或调整真实环境测试的开关。

## Decisions

- 单一模块负责验收的不变量放在 `tests/<module>/`，即使它注入其他组件。跨模块完整调用链、共享模型/schema 契约保留根目录。Lifecycle 装配测试归 lifecycle；Workflow 配置覆盖到真实采集/投递/恢复的贯通测试保留根目录。
- 前端是独立包，沿用 `frontend/tests/unit` 与 `frontend/tests/e2e`，保留既有 Vitest/Playwright 发现规则；补充文件说明及根测试导航，不混入 Python 测试目录。
- 采用文件顶部 Python docstring / TypeScript 块注释，说明测试逻辑与真实/替身依赖，避免逐行复述代码。README 提供职责导航而不重复每项断言。
- 使用显式测试包导入。Workflow 专属共享对象提取到 `tests/workflow/helpers.py`；跨模块 LangChain 替身留在根目录，不复制实现，不修改 sys.path。
- 独立 change 根 `tasks.md` 作为 OpenSpec CLI 唯一进度入口；用户指定的 `task.md` 保存依据与详细验证证据，由入口链接，不建立第二套进度清单。

## Risks / Trade-offs

迁移可能影响 Python 导入、子进程源码路径及手动运行命令。以收集用例对比、分组回归和单文件运行验证；子进程路径按新目录深度更新。真实 HTTP/模型测试仍需要原有服务或显式开关，缺少依赖时如实报告，不能用跳过逻辑伪装通过。

## Migration Plan

移动并标注测试；修正导入和路径；补充 README；比对用例集合并执行验证；记录结果。回退可恢复文件位置和导入，不涉及数据迁移。

## Open Questions

无；执行范围由用户本次请求确定。
