# Headless Backend QA 状态

更新时间：2026-10-06

## 范围与运行方式

- 只运行后端 pytest，不启动 headed 浏览器。
- 覆盖 `tests/interaction`、`tests/lifecycle`、`tests/config`、`tests/collection`、`tests/agent`、`tests/workflow`、`tests/channel` 下全部 `test_*.py`：75 个模块，共收集 753 个 pytest 节点。
- 每条 pytest 命令均经 `rtk proxy timeout 60s rtk uv run --no-sync pytest ...` 执行；长模块按 pytest node 拆分。
- 项目环境为 Python 3.11.15 / pytest 9.1.1（`.venv`）。直接 `rtk pytest` 使用 Python 3.10 且缺少项目依赖，首次收集失败；改用项目 `.venv` 后收集成功。此项归类为运行环境装配问题。
- `src/workflowweave/interaction/test_channel_routers.py` 文件名符合 `test_*.py`，但它是路由实现而没有 pytest 测试函数；显式收集结果为 `no tests collected`，不计入 753 个节点。

## 覆盖矩阵

| 测试目录 | 节点数 | PASS | FAIL | TIMEOUT | 状态说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| interaction | 61 | 61 | 0 | 0 | 全部通过 |
| lifecycle | 38 | 38 | 0 | 0 | 全部通过 |
| config | 119 | 119 | 0 | 0 | 全部通过 |
| collection | 31 | 31 | 0 | 0 | 全部通过 |
| agent | 157 | 157 | 0 | 0 | 全部通过 |
| workflow | 201 | 199 | 2 | 0 | 两个节点在并发整模块首跑出现失败标记；隔离复跑通过，按 flaky/FAIL 保留 |
| channel | 146 | 144 | 1 | 1 | Email 有一条时限敏感失败；Feishu SDK 生命周期节点超时 |
| **合计** | **753** | **749** | **3** | **1** | FAIL 包含隔离复跑通过的时序敏感节点；整模块超时另列，不重复计为节点 TIMEOUT |

## 失败与超时归因

- **测试时限敏感：** `tests/channel/test_email_channel.py::test_rejections_disconnects_and_timeouts_never_retry[recipient-False-0]` 使用 `timeout=.1`。首次整模块运行和一次独立复跑均失败，错误是 `delivery_uncertain` 为 `True`；后续带 locals 的独立复跑通过。当前证据指向测试对 100ms SMTP 时限/调度时序敏感，未确认产品缺陷；未修改测试。
- **并发运行时 flaky：** `tests/workflow/test_workflow_process_recovery.py` 的整模块首跑与其他回归并行，pytest 输出两个 `F` 后在 60 秒被终止，未留下失败 traceback/最终汇总。4 个节点随后逐项隔离运行均通过。矩阵按首跑保留两个 flaky/FAIL，分类为并发负载下的测试运行不稳定，未确认产品缺陷。
- **产品问题：** `tests/channel/test_feishu_plugin.py::test_real_lark_websocket_client_private_lifecycle_contract` 独立运行超过 60 秒。对应产品路径 `plugins/channel/feishu/channel.py` 的 `_load_sdk()` 等待导入 `lark_oapi`；在本环境中直接导入也超过 60 秒，SDK 顶层初始化会导入整组 API。已记录到 [Feishu SDK 导入问题](docs/qa-headless-backend-feishu-sdk-import.md)。该节点未进入 WebSocket 生命周期断言；同模块前 8 个节点通过。
- **已拆分恢复：** `tests/workflow/test_stage_resume.py` 整模块超过 60 秒；前 9 个节点通过，余下 2 个节点各自复跑通过，11 个节点最终均为 PASS。`test_workflow_recovery.py` 拆成 5 组，每组 60 秒上限内通过，共 44 PASS。

## 证据位置

逐模块输出保存在 `/tmp/qa-headless-backend-*.log`。收集数量记录在 `/tmp/qa-headless-backend-collect-*.log`。测试和源代码均未修改。
