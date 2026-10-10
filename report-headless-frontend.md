# Headless Frontend QA 报告

日期：2026-10-06（Asia/Shanghai）

## 执行边界

- 仅运行前端 unit、typecheck、architecture、production build，以及 Playwright Chromium 无头 smoke。
- 所有 shell 命令均通过 `rtk`；未启动 headed 浏览器。
- 未修改测试/spec；工作区原有产品和测试改动保持不变。
- 未创建 `docs/qa-headless-frontend-*.md`：本轮确认的失败均为测试 fixture/装配问题，没有确认产品代码 bug。

## 总结

| 检查 | 结果 | 命令耗时 |
| --- | --- | ---: |
| Unit | 266/267 通过；1 失败 | 180.20s |
| Typecheck | 通过 | 17.13s |
| Architecture | 通过（200 源文件；44 fixture） | 7.22s |
| Production build | 通过（4220 modules） | 83.66s |
| Playwright smoke | 14/18 通过；4 失败；另有 1 次端口装配失败后以备用端口重试 | 125.03s（重试） |

## Unit tests

命令：`rtk proxy /usr/bin/time -p sh -c 'mkdir -p /tmp/logagent-qa-headless && npm test -- --reporter=json --outputFile=/tmp/logagent-qa-headless/vitest.json'`（工作目录 `frontend/`）。

| 测试文件 | 通过 | 失败 | 文件耗时 | 状态 |
| --- | ---: | ---: | ---: | --- |
| `tests/unit/agent-adapter.test.ts` | 4 | 0 | 0.13s | 通过 |
| `tests/unit/agent-app-route.test.ts` | 1 | 0 | 1.23s | 通过 |
| `tests/unit/agent-channel-api.test.ts` | 2 | 0 | 0.02s | 通过 |
| `tests/unit/agent-components.test.ts` | 8 | 0 | 0.73s | 通过 |
| `tests/unit/agent-composer.test.ts` | 4 | 0 | 0.09s | 通过 |
| `tests/unit/agent-controllers.test.ts` | 5 | 0 | 0.01s | 通过 |
| `tests/unit/agent-models.test.ts` | 2 | 0 | 0.01s | 通过 |
| `tests/unit/agent-protocol.test.ts` | 5 | 0 | 0.00s | 通过 |
| `tests/unit/agent-settings-modal.test.ts` | 3 | 0 | 1.00s | 通过 |
| `tests/unit/agent-stream.test.ts` | 2 | 0 | 0.14s | 通过 |
| `tests/unit/agent-view.test.ts` | 13 | 0 | 3.18s | 通过 |
| `tests/unit/agent_chat.test.ts` | 7 | 0 | 0.04s | 通过 |
| `tests/unit/ai-model-select.test.ts` | 5 | 0 | 0.64s | 通过 |
| `tests/unit/api.test.ts` | 20 | 0 | 0.03s | 通过 |
| `tests/unit/app-router.test.ts` | 1 | 0 | 0.01s | 通过 |
| `tests/unit/async-task.test.ts` | 1 | 0 | 0.00s | 通过 |
| `tests/unit/channel-conversation.test.ts` | 5 | 0 | 0.27s | 通过 |
| `tests/unit/continue-in-agent.test.ts` | 2 | 0 | 0.20s | 通过 |
| `tests/unit/editor.test.ts` | 8 | 0 | 1.47s | 通过 |
| `tests/unit/foundation-controllers.test.ts` | 3 | 0 | 0.02s | 通过 |
| `tests/unit/frontend-task1.test.ts` | 3 | 0 | 0.89s | 通过 |
| `tests/unit/http-transport.test.ts` | 8 | 0 | 0.04s | 通过 |
| `tests/unit/json-field.test.ts` | 1 | 0 | 0.31s | 通过 |
| `tests/unit/mcp-server-editor.test.ts` | 5 | 0 | 0.74s | 通过 |
| `tests/unit/monitoring.test.ts` | 5 | 0 | 0.54s | 通过 |
| `tests/unit/parameter-field.test.ts` | 15 | 0 | 2.92s | 通过 |
| `tests/unit/provider-api.test.ts` | 2 | 0 | 0.01s | 通过 |
| `tests/unit/provider-editor.test.ts` | 11 | 0 | 2.82s | 通过 |
| `tests/unit/provider-proxy.test.ts` | 2 | 0 | 1.23s | 通过 |
| `tests/unit/provider-view.test.ts` | 3 | 0 | 1.44s | 通过 |
| `tests/unit/query.test.ts` | 6 | 0 | 0.01s | 通过 |
| `tests/unit/report.test.ts` | 6 | 0 | 0.25s | 通过 |
| `tests/unit/resource-config.test.ts` | 6 | 0 | 2.84s | 通过 |
| `tests/unit/resources/resource-ownership.test.ts` | 4 | 0 | 0.03s | 通过 |
| `tests/unit/resources/source-editor.test.ts` | 8 | 0 | 1.89s | 通过 |
| `tests/unit/run-detail.test.ts` | 4 | 0 | 0.03s | 通过 |
| `tests/unit/run-stream.test.ts` | 8 | 0 | 0.02s | 通过 |
| `tests/unit/runs-actions.test.ts` | 7 | 0 | 0.01s | 通过 |
| `tests/unit/runs-api.test.ts` | 1 | 0 | 0.01s | 通过 |
| `tests/unit/runs-view.test.ts` | 3 | 0 | 2.94s | 通过 |
| `tests/unit/schema-validation.test.ts` | 8 | 0 | 0.25s | 通过 |
| `tests/unit/source-sharing.test.ts` | 5 | 0 | 0.25s | 通过 |
| `tests/unit/system-controllers.test.ts` | 3 | 0 | 0.01s | 通过 |
| `tests/unit/workflow-agent-tasks.test.ts` | 7 | 0 | 0.75s | 通过 |
| `tests/unit/workflow-backup-policy.test.ts` | 2 | 0 | 0.24s | 通过 |
| `tests/unit/workflow-bindings.test.ts` | 3 | 0 | 0.80s | 通过 |
| `tests/unit/workflow-editor.test.ts` | 9 | 0 | 0.02s | 通过 |
| `tests/unit/workflow-model-catalog.test.ts` | 3 | 0 | 0.72s | 通过 |
| `tests/unit/workflow-module-ui.test.ts` | 7 | 0 | 1.69s | 通过 |
| `tests/unit/workflow-page-query.test.ts` | 2 | 0 | 0.39s | 通过 |
| `tests/unit/workflow-prompt-save.test.ts` | 0 | 1 | 1.07s | 失败 |
| `tests/unit/workflow-schedule.test.ts` | 6 | 0 | 0.88s | 通过 |
| `tests/unit/workflow-source-confirmation.test.ts` | 2 | 0 | 0.16s | 通过 |

### Unit 失败堆栈与归因

`frontend/tests/unit/workflow-prompt-save.test.ts`：

```text
AssertionError: expected "spy" to be called once, but got 0 times
  at frontend/tests/unit/workflow-prompt-save.test.ts:123:19
```

失败前置：fixture 中第二个分析任务的 `user_prompt` 为空，前端 `validateWorkflow` 按当前 prompt contract 拒绝保存，因此 `replace` 未调用。依据 `openspec/changes/align-workflow-prompt-contract/design.md` 与 `specs/workflow-prompts/spec.md`，分析差异提示词必须由用户填写且非空；这是测试 fixture 与契约不一致，不是产品代码 bug。

## Typecheck / architecture / build

- Typecheck：`rtk proxy /usr/bin/time -p npm run typecheck`，通过，17.13s。
- Architecture：`rtk proxy /usr/bin/time -p npm run architecture:check`，通过；`architecture check passed (200 files; retired roots forbidden)`，fixture `44 files` 通过，7.22s。
- Build：`rtk proxy /usr/bin/time -p npm run build`，通过，Vue typecheck + Vite build，4220 modules，83.66s。仅有 zod 第三方包 Rollup 注释位置 warning，不影响产物。

## Playwright smoke

配置：`frontend/playwright.config.ts`；项目为 Chromium，未设置 headed 覆盖，使用默认 headless。

首次命令：`rtk proxy /usr/bin/time -p npm run test:e2e`。

首次装配失败（2.72s）：

```text
Error: http://127.0.0.1:14300 is already used, make sure that nothing is running on the port/url or set reuseExistingServer:true in config.webServer.
```

端口占用者是共享环境中已有的 workflowweave/vite QA 进程；未中断它。随后使用配置支持的备用端口重试：

`rtk proxy /usr/bin/time -p env WORKFLOWWEAVE_E2E_BACKEND_PORT=14301 WORKFLOWWEAVE_E2E_FRONTEND_PORT=13001 npm run test:e2e`。

| 测试文件 | 通过 | 失败 | 文件结果 |
| --- | ---: | ---: | --- |
| `tests/e2e/agent-ui.spec.ts` | 7 | 0 | 通过 |
| `tests/e2e/frontend.spec.ts` | 4 | 4 | 失败 |
| `tests/e2e/monitoring.spec.ts` | 1 | 0 | 通过 |
| `tests/e2e/resources.spec.ts` | 2 | 0 | 通过 |

### Playwright 失败堆栈与归因

1. `tests/e2e/frontend.spec.ts:6`（0.226s）：
```text
Error: {"error":{"code":"validation","message":"请求参数或资源结构不符合契约","details":{"errors":[{"path":["body","analyses",0],"reason":"value_error"}]}}}
  at frontend/tests/e2e/frontend.spec.ts:44:48
```
创建请求的 `analyses[0].user_prompt` 缺失，当前后端 AnalysisTask 契约要求非空。测试装配/fixture 问题。

2. `tests/e2e/frontend.spec.ts:216`（8.6s）：
```text
Error: expect(page).toHaveURL(expected) failed
Expected pattern: /\/workflows$/
Received string: "http://127.0.0.1:13001/workflows/new"
  at frontend/tests/e2e/frontend.spec.ts:282:22
```
页面保存仍在 `/workflows/new`；该用例创建的分析任务未填写必填差异提示词，前端校验阻止保存。测试 fixture 与当前契约不一致。

3. `tests/e2e/frontend.spec.ts:377`（60.0s timeout）：
```text
Test timeout of 60000ms exceeded.
Error: page.waitForResponse: Test timeout of 60000ms exceeded.
  at frontend/tests/e2e/frontend.spec.ts:516:33
```
保存 workflow 未产生 POST，因为页面同样被空 `user_prompt` 的前端校验拦截；等待响应因此超时。测试 fixture/断言前置条件问题。

4. `tests/e2e/frontend.spec.ts:684`（0.241s）：
```text
Error: {"error":{"code":"validation","message":"请求参数或资源结构不符合契约","details":{"errors":[{"path":["body","analyses",0],"reason":"value_error"}]}}}
  at frontend/tests/e2e/frontend.spec.ts:731:52
```
两个 workflow 创建 payload 都将 `user_prompt` 设为空字符串，后端按契约拒绝。测试 fixture 问题。

## 结论

- 静态检查和生产构建通过。
- 当前 unit 基线只有 1 个失败；Playwright 重试 smoke 有 4 个失败。失败均能由当前 prompt contract 的非空 `user_prompt` 要求或外部端口占用解释，未发现需要记录产品缺陷的证据。
- 未修改任何测试/spec，也未启动 headed 浏览器。
