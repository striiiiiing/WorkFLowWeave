# 测试维护执行记录

## 依据与范围

- 用户要求：每个测试模块描述逻辑；模块专属测试放 `tests/<模块名>`，其他留外层；
- 本次属于测试结构整理，依据 [本次 proposal](proposal.md)、[本次 design](design.md) 与 [OpenSpec 存放约定](../../README.md)，不修改原业务设计。
- `tasks.md` 是 CLI 唯一任务清单，本文件保存详细决策与验证证据；不继续向原总变更追加独立任务。
- 模块目录沿用生产包名称 `ai/channel/collection/config/interaction/lifecycle/workflow`。判断依据是被测职责而非 import 数量：历史采集器归 collection，SessionStore 与恢复归 workflow，应用装配归 lifecycle；共享 contracts/schema/session models 及 starter resources、跨模块 Workflow integration/overrides 留根目录。
- 前端独立测试环境依据 `frontend/package.json`、`vitest.config.ts` 与 Playwright 配置，继续使用包内 `frontend/tests/unit` 和 `frontend/tests/e2e`，每个文件同样补说明。
- 新增包标记和明确导入，取代依赖 pytest 临时搜索路径的裸导入；Workflow 辅助对象从测试文件提取，避免第二份实现。
- 说明采用中文文件级 docstring/块注释，描述覆盖逻辑、构造/执行/断言方式及真实依赖；不机械重复每行代码。
- 后端测试每组命令硬超时 60 秒，依据用户 AGENTS.md；不改变生产或测试内部默认时限。网络验收测试保留原启用条件。

## 验证结果

- 迁移前收集基线：626 项（10.00 秒），326 个未展开参数化的测试函数。初始工作区测试文件无未提交修改；保存 HEAD AST 用于比对断言行为。
- 首批回归：interaction/lifecycle 46 passed（18.25 秒）；根目录共享契约与跨模块集成 158 passed（15.99 秒），命令均设 60 秒硬超时。
- 前端原有 3 个单测文件共 19 passed（41.55 秒）。首次执行缺少 Rollup Linux 可选依赖，补齐本机 node_modules 后通过，未修改 package.json/package-lock.json。
- 前端类型检查首次通过；随后构建因并发编辑的 ResourceEditor.vue、SourceStepCard.vue 引用尚不存在的 ParameterField.vue 失败。运行期间另一个工作流新增 editor.test.ts 并修改多处 frontend/src 和 src/logagent/models.py；这些不是本次修改，不覆盖或回退。构建与浏览器验收不能据此前单测结果视为通过。
- OpenSpec：`openspec validate organize-test-modules --strict --no-interactive` 通过；`skip_specs: true` 被 CLI 识别为无业务行为增量。
- 后续回归：config/collection 216 passed（13.52 秒）；channel 84 passed（4.76 秒）；workflow（不含进程强退）61 passed（15.03 秒）；进程强退 3 passed（38.43 秒）。后端命令均使用 `timeout 60s`。
- AI 分组：env/service 23 passed、3 skipped、2 failed（23.92 秒）；channels 8 passed、2 skipped（0.65 秒）。失败原因是本地 `mock` 端点返回 `LOGAGENT_OK`，现有 `assert_success` 要求包含“测试”，与目录/导入无关；保留原断言。live 文件以及最初 AI 整组命令到 60 秒被 timeout 终止，不能报告通过。Qwen 跳过来自原有显式开关，未新增跳过策略。
- 迁移后收集 627 项（12.61 秒）：原 626 项逐一保留且无重复，多出并发任务新增的 `test_workflow_frontend_defaults.py::test_counts_default_on_but_explicit_saved_false_is_preserved`。该新增文件不属于本次整理范围，未移动或标注。
- 静态审查：原 28 个后端测试文件及 4 个原辅助/包文件均有模块说明；新增包文件和 Workflow helpers 也有说明。提取的 AI/Channel/Collector/snapshot AST 与原实现一致，未复制实现。前端原 5 个测试文件及启动器补充说明；并发新增 editor.test.ts 未改动。
- 原 326 个测试函数 AST 中，320 个不变；6 个发生并发产品变更，均为输入增加 `source: success (1)` 后对应期望调整，涉及 integration、overrides、recovery、process_recovery；子进程嵌入程序也有同类期望变更。保留这些并发编辑，不将其误判为本次说明修改；相关常规集成/恢复重跑 49 passed（24.92 秒），进程恢复验证已覆盖更新后的期望。
- Ruff 全部通过；前端本次 5 个测试文件 Prettier 检查通过；本次范围 `git diff --check` 通过。所有新增文档本地链接有效。未修改生产实现、依赖声明或旧 proposal/design。
- 最小烟测由新路径下单文件进程恢复测试承担：实际启动子进程、强退、重开并恢复成功，覆盖迁移后的 `__file__` 路径。前端仅注释变化，构建已尝试但受并发产品编辑阻断，因此没有把浏览器 E2E 记为通过。

- AI live 定向诊断（`-x --tb=short`）：1 passed、1 skipped、1 failed（17.61 秒），失败位于 `test_thinking_controls[mock-thinking_off]` 的同一成功正文标记断言，确认外部响应与现有验收预期不一致。
