# 后端业务压测证据（2026-10-08）

本轮验证应用在小资源预算下执行实际编排链路，结果见根 README 的“按业务链路压测”。不测真实模型质量或推理吞吐，不与其他 Agent 产品做同负载效率比较。

## 环境与实现

- 本地 WSL2 / Linux 6.6.87.2，宿主 12 个逻辑 CPU、约 7,845 MiB 内存；Python 3.11.15、FastAPI 0.141.1、Uvicorn 0.53.0、LangGraph 1.2.12、MCP SDK 1.30.0。
- HEAD 为 `6c3bebbb47418f06787e049c824155cabf9a40cf`，运行的是包含未提交变更的工作区，不能仅用 HEAD 还原。`source-manifest.json` 记录源码、插件、pyproject.toml、uv.lock 的 SHA256 与实际依赖版本。
- cgroup v2 实际读回 `cpu.max=100000 100000`、`memory.max=536870912`、`memory.swap.max=0`。CPU 时间配额可在多个 CPU 上调度，不是单核 affinity，更不是同型号 1 vCPU 云主机模拟。后端 CLI/MCP 子进程继承同一 cgroup。
- 独立配置与临时数据目录；仅读取服务器现状，没有远端加压或生产数据修改。模型夹具和生成器在 cgroup 外。模型使用 HTTP/SSE、20 帧 x 50ms、1,043 字节固定正文，未推理。
- MCP 为真实 stdio 协议的确定性工具；CLI 为真实 cat 文件。100 条输入原始 JSON 34,794 字节，1,000 条 350,513 字节。MCP 的协议响应可能额外包含文本与结构化表示，原始 JSON 大小不等于整个线上的响应字节数。
- 新闻、股票、issue 按产品拓扑运行；新闻保留单任务汇总优化，不假定每次都产生额外汇总模型请求。工作流均保存默认归档，使用真正的文件通知渠道。未启用多轮 Agent 工具调用与第三方平台连接。

## 数据文件

| 文件 | 含义 |
| --- | --- |
| `memory-limit-attempt.json` / `memory-limit-backend.log` | 同一实例的初始空闲、日常、突发完整结果，以及较大输入 OOM 的未完成阶段采样 |
| `memory-limit-systemd.log` | systemd 明确记录 OOM killer 终止服务、SIGKILL；systemd 摘要的 MemoryPeak 在 cgroup 删除后不可靠，不作为峰值依据 |
| `result.json` / `backend.log` | 新隔离实例的初始空闲、180 秒连续运行与30秒恢复，完整成功，结束健康 ready |
| `initial-attempt.json` / `initial-attempt-backend.log` | 第一版批次立即重提导致 429，阶段中断；不纳入成功表 |
| `source-manifest.json` | 测量开始时产品源码/依赖哈希；夹具修正未改产品代码 |

成功表分别取 `memory-limit-attempt.json` 的 daily/burst 和 `result.json` 的 soak/recovery-idle，不能合并为单实例无中断运行。首轮429和较大输入OOM作为独立边界保留，未以重试抹去失败。

## 负载与口径

- 日常：60秒，浏览2请求/秒，新闻每15秒一次，共4次。
- 突发：60秒，浏览8请求/秒，每15秒一批4工作流，共4批16次；每批业务归档读取后显式空闲5秒。默认运行准入为4，SSE终态早于全部defer清理完成。
- 连续：180秒，浏览2请求/秒，每15秒一批新闻/股票/issue，共36次；每批末尾同样空闲5秒。
- 总计56次成功工作流、1,296次普通API调用、56条SSE订阅、72次成功文件通知。每次工作流普通API计入触发、会话读取及4个阶段读取；SSE耗时/帧数单独保存在runs中，未计入普通API延迟分位。
- CPU为整个后端cgroup CPU时间差除以阶段实际耗时，单核=100%；批间休息包含于均值。突发CPU throttled_usec累计约48.44秒，不能等同于用户等待时间。生成器CPU不计入后端。
- 250ms资源采样；memory.current是总内存，working_set扣除inactive_file。阶段峰值为采样峰值，连续实例另有内核memory.peak=367.22MiB（含启动/预检）。swap均为0。
- 连续实例最终memory.events所有计数为0、健康ready；恢复阶段峰值276.91MiB，不能仅凭180秒证明无内存泄漏。SQLite数据库、WAL、SHM在结束时共约44.10MiB，包含预检和历史/checkpoint，不据此线性预测长期磁盘增长。
- 大输入阶段接近512MiB后发生OOM，4次提交中仅2次完成全部客户端校验；后端被终止，未完成的延迟/CPU不得作为成功阶段统计。首个HTTP断连后来被采样器cgroup消失异常覆盖，已修正实验脚本并保留systemd根因证据。

## 复现

需要Linux cgroup v2、可用的systemd用户服务，以及本项目依赖已安装的Python环境；在仓库根目录运行，4399与9919端口须空闲。默认全部普通输入阶段约6分钟加启动/预检；每次新建临时状态，最后停止用户服务并删除临时数据。

```bash
.venv/bin/python artifacts/backend-business-pressure-20261008.py \
  --output artifacts/backend-business-pressure-reproduction
```

单独复现连续阶段：

```bash
.venv/bin/python artifacts/backend-business-pressure-20261008.py \
  --stages idle,soak,recovery-idle --soak-seconds 180 \
  --output artifacts/backend-business-pressure-soak-reproduction
```

显式复现较大输入边界会使**隔离服务**可能OOM，脚本将其记录为失败并退出；不是默认路径：

```bash
.venv/bin/python artifacts/backend-business-pressure-20261008.py \
  --stages idle,daily,burst,large-input \
  --output artifacts/backend-business-pressure-boundary-reproduction
```

用户服务OOM后如systemd保留failed状态，再次测试前用 `systemctl --user reset-failed workflowweave-business-pressure` 清理该测试服务的失败状态。不要在生产服务上套用该方案或调整生产并发/内存来强行获取成功结果。
