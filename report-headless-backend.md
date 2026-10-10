# Headless Backend QA 报告

## 结论

按请求运行 interaction、lifecycle、config、collection、agent、workflow、channel 七个 pytest 范围，共 75 个测试模块、753 个节点。按首次完整回归中观察到的结果统计为 **749 PASS、3 flaky/FAIL、1 TIMEOUT**；其中 3 个失败节点隔离复跑后通过，保留 FAIL 以体现首跑波动。一个 Feishu SDK 导入节点在独立的 60 秒硬超时内仍未完成，归类为产品路径性能问题。未修改测试或产品代码。

## 覆盖结果

| 范围 | 节点 | PASS | FAIL | TIMEOUT |
| --- | ---: | ---: | ---: | ---: |
| `tests/interaction` | 61 | 61 | 0 | 0 |
| `tests/lifecycle` | 38 | 38 | 0 | 0 |
| `tests/config` | 119 | 119 | 0 | 0 |
| `tests/collection` | 31 | 31 | 0 | 0 |
| `tests/agent` | 157 | 157 | 0 | 0 |
| `tests/workflow` | 201 | 199 | 2 | 0 |
| `tests/channel` | 146 | 144 | 1 | 1 |
| **合计** | **753** | **749** | **3** | **1** |

FAIL 统计保留首跑结果：隔离复跑通过的节点仍记为 flaky/FAIL；TIMEOUT 只统计独立节点仍未结束的情况。拆分后已通过的整模块超时不重复算作节点 TIMEOUT。

## 需要关注的结果

**测试时限敏感，未确认产品缺陷。** `tests/channel/test_email_channel.py::test_rejections_disconnects_and_timeouts_never_retry[recipient-False-0]` 在整模块运行和一次节点复跑中失败，断言收到 `recipient` 拒绝时 `delivery_uncertain` 应为 `False`；测试配置的 SMTP 总时限只有 100ms。随后同节点独立复跑通过。该结果不稳定且受极短测试时限影响，因此保留为 FAIL/flake 记录，不创建产品缺陷报告，也没有改测试。

**产品路径超时。** `tests/channel/test_feishu_plugin.py::test_real_lark_websocket_client_private_lifecycle_contract` 在单节点 60 秒硬超时内无输出并被终止。诊断显示，测试在生命周期断言前导入 `lark_oapi`；同一导入在独立 60 秒硬超时中也未完成。产品的 Feishu `_load_sdk()` 等待同一导入，而 SDK 顶层初始化会导入整组 API。该问题已单独记录在 [Feishu SDK 导入问题](docs/qa-headless-backend-feishu-sdk-import.md)。Feishu 模块其余 8 个节点通过。

**大模块超时已按节点解决。** `stage_resume` 整模块运行触及 60 秒上限，但 11 个节点最终均通过；`workflow_process_recovery` 整模块在并发运行时触及上限，4 个节点各自复跑均通过。`workflow_recovery` 使用 10 节点分组运行，44 个节点全部通过。这些整模块超时不计入最终节点 TIMEOUT 数。

`workflow_process_recovery` 的并发整模块首跑在被终止前输出两个 `F`，但没有最终 traceback 或汇总；对应节点隔离复跑通过，因此计入 workflow 的两个 flaky/FAIL，分类为并发负载下的测试运行不稳定，尚无产品缺陷证据。

## 环境与命令

仓库要求 Python ≥3.11。全局 `rtk pytest` 使用 Python 3.10，缺少 `workflowweave` 和项目依赖，导致首次收集报导入错误；改用仓库 `.venv` 的 `rtk uv run --no-sync pytest` 后，七个目录均成功收集。每条 pytest 命令均由 `timeout 60s` 硬限时。未启动 headed 浏览器。

所有分目录收集及逐模块/逐节点日志位于 `/tmp/qa-headless-backend-*.log`；当前目录 `src/workflowweave/interaction/test_channel_routers.py` 是路由实现文件，显式收集无测试节点，不属于覆盖数量。
