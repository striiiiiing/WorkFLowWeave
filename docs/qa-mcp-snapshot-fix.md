# MCP Workflow 快照绑定修复

## 问题与参考

2026-10-06，用户要求将 `ssh myserver:/home/user/opt/workflowServer/docs/test-deployment-20261006.md` 中适用于本仓库的问题一并处理。远端报告及合并提交 `ac92aceac0f97d38d04c52e20d4cfd1229fc29be` 说明：单来源 MCP collect 正常，Workflow 却报 `mcp_out_of_scope`，因为执行上下文没有携带冻结快照中的 MCP 服务绑定。

## 修改方案

`WorkflowContext.__post_init__` 在唯一的执行上下文装配边界，用冻结 `snapshot.mcp_servers` 替换采集上下文绑定，并通过已有 `copy_model` 深复制每份配置。手动、定时与恢复都复用这一边界；不在各入口重复补绑定，不读取运行时最新资源配置，也不修改调用方传入的上下文或快照。

本地已存在这一修复的初稿和真实 stdio MCP 回归用例，本次保留，并将配置值的浅复制补为与远端一致的深复制。测试覆盖默认上下文和显式空上下文；首次运行成功后，故意改变资源仓库中的 MCP command，再从 collect 恢复，要求仍使用原冻结配置成功采集。

## 适用范围

远端同轮前端旧模型导入和重复文件问题已纳入 `qa-model-import-fix.md`。远端私有 QwenPaw 数据格式、Memos 分段投递和 QQ 部署代理修复没有本仓库对应实现，不把远端业务数据、凭据或私有部署配置复制进公共源码。

阶段正文 `content.status` 的代码核对：`CheckpointArchiver._phase` 保存阶段 checkpoint 当时的工作流全局状态；在 finish 之前它通常仍为 running。`read_phase` 读取固定历史版本，前端 `parsePhase` 对 collect/analyze/notify 显示各条目自己的状态，只有 finish 用正文的全局 status。因而不将所有早期历史正文按最终 session 状态覆盖；实际终态展示与恢复查询仍由子代理验证。

## 验证

GPT 6 Luna 后端测试子代理复验 `tests/workflow/test_mcp_cli_flow.py`：4 项通过，耗时 33.59 秒，实际启动 stdio MCP 进程并验证默认/显式空上下文和 collect 恢复。日志见 `/tmp/logagent-tabbit-qa/pytest-workflow-mcp.log`。完整 HTTP MCP 与 UI 联调结果仍待补充。所有后端单测命令保留 60 秒硬超时；使用真实 AxonHub Provider、专用测试密钥和 `mock` 模型，不替换模型传输或合成成功响应。
