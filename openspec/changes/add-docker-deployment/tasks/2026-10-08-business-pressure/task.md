# 基于业务的隔离后端压测

## 依据、决策与范围

- 用户要求实际压测后端、结果写入 README，并强调“低需求 + 低占用”、原低配服务器不可用、按项目业务设计方案。
- 参考本变更 proposal.md / design.md 的单进程生命周期、默认并发、真实健康检查，以及 README 的新闻压缩、股票 fan-out/fan-in、GitHub issue 分工三种业务拓扑。设计与产品代码不变，这是实验和文档任务。
- 2026-10-08 只读检查 myserver：4 vCPU、7,948 MiB 内存、load average 5.10、约 5,891 MiB swap 使用量。共享服务和换页会污染资源结论，选择本地 WSL2 的独立数据目录与 systemd 用户服务。
- cgroup v2 明确限制 CPUQuota=100%、MemoryMax=512M、MemorySwapMax=0；512 MiB 是待验证的应用预算，不是整机最低内存声明。CPUQuota 100% 表示一颗逻辑核心的总 CPU 时间，允许调度到多个核心，不能称为同型号 1 vCPU 云主机。
- 后端采用当前工作区源码和现有 .venv；不复用生产资源、凭据、数据库。模型服务、生成器在 cgroup 外，后端 CLI/MCP 子进程在 cgroup 内。
- 只将模型替换为明确的本地 OpenAI Chat Completions SSE 夹具，每调用 20 帧、帧间隔 50ms、约 1 秒、固定输出约 1KiB。通过真实 HTTP/SDK/AIService 路径执行，避免模型计费与上游波动掩盖后端开销；不得宣称模型质量、真实端到端模型速度或平台通知容量。
- 来源为真实 CLI cat JSON 与真实 stdio MCP 工具，默认 100 条、较大输入 1,000 条；数量是实验负载，记录 UTF-8 原始字节数。MCP 夹具生成确定性新闻/日志式记录，外部网站和搜索服务没有参与。
- 三类工作流：新闻 1 分析 + fan-in（保留单任务优化默认值）、股票 3 并行分析 + fan-in、issue 2 独立分析不汇总。通知采用产品的文件渠道，以可核验写入覆盖通知链路，不向他人发消息。
- 使用默认 max_concurrent_runs=4（src/workflowweave/models.py）；4 工作流突发表示碰到已配置的运行上限，不当作 API 并发上限或吞吐极限。

## 负载与验证

- 空闲 15 秒；日常 60 秒，2 API 请求/秒 + 每 15 秒一次新闻工作流。
- 突发 60 秒，8 API 请求/秒 + 4 批 4 工作流；较大输入 20 秒，2 API 请求/秒 + 4 个 1,000 条输入的股票型工作流。
- 连续运行 180 秒，2 API 请求/秒 + 每 15 秒一批新闻/股票/issue；180 秒是短时资源趋势验证，不是长期耐久测试。最后空闲恢复 30 秒。
- API 读取工作流、来源、20 条历史页和健康报告；每次工作流通过 SSE 等到终态，再读取会话与 collect/analyze/aggregate/notify 归档，验证采集成功、最终正文和文件通知成功。
- 250ms 采样 cgroup CPU、总内存、扣除 inactive_file 的工作集、swap、内存事件；同时记录 memory.peak 生命周期峰值。统计包含所有受控后端子进程，生成器不计入。
- 实验验收目标：全部业务运行完成、API/归档/SSE/文件通知校验通过、无 OOM/换页、末尾 ready；日常 CPU 单核均值低于 10%、轻载 API P95 低于 100ms 为本轮选定的观察阈值，不是既有产品 SLA。
- 每阶段保存原始请求耗时、逐次业务会话结果、逐帧数、逐次模型请求字节/哈希、资源采样；错误明确终止并保存诊断。用户服务退出时 stop，临时状态删除。

## 首次实验与方案校正

- 首轮日常阶段 4 次业务运行和 144 次 API 请求全部成功，P95 12.85ms、CPU 单核均值 12.56%、总内存采样峰值 262.66MiB。CPU 未满足预设的 10% 观察阈值，不调整阈值掩盖结果。
- 首轮突发第一批完成后，马上提交第二批收到 3 次明确的 HTTP 429 / capacity_exhausted，实验停止。证据保留为 initial-attempt.json 与 initial-attempt-backend.log，不将未完成阶段的性能数值纳入最终表。
- 依据 workflow/graph/subgraph/nodes/cleanup.py 与 execution/maintenance.py：finish 业务终态后 defer 节点仍会交接归档、清理 checkpoint，RunCoordinator 的任务完成回调才释放槽位。因此 SSE terminal 不能当作所有后台资源已释放的信号。
- 复测每批业务结束后显式空闲 5 秒，并将突发改为每 15 秒一批、共 4 批。5 秒是本次负载模型的退潮时间，不是产品承诺或自动重试；再次出现 429 仍直接保存失败并停止。表中说明间歇和实际耗时，不将批间休息后的均值称为持续饱和负载 CPU。
- 复测突发 16 次运行、576 次 API 请求全部通过，API P95 139.03ms、业务 P95 9.013 秒、cgroup 总内存峰值 386.53MiB。
- 随后的 4 个 1,000 条输入运行触发 cgroup OOM；systemctl Result=oom-kill、ExecMainStatus=9，memory.current 最后采样接近 512MiB。证据保留为 memory-limit-attempt.json / memory-limit-backend.log / memory-limit-systemd.log。失败阶段不写成完整成功压测。
- 首次采样器的 FileNotFoundError 覆盖了原始 HTTP 断连异常：cgroup 在 OOM 后消失。已改为记录采样器退出诊断、保留原始错误，并用 TaskGroup 在失败时取消其余请求任务。此为实验脚本的根因修正，产品未改。
- 连续与恢复阶段用全新的同配置实例单独执行；最终 README 分别引用两次运行，不拼接成同一实例连续无失败。较大输入作为显式 --stages large-input 的边界实验，默认复测只跑普通输入，以避免无意反复 OOM。

## 实施状态

- [x] 核对业务路由、工作流拓扑、CLI/MCP、文件通知和单进程运行实现。
- [x] 检查远端现状，验证本地 cgroup 限制生效。
- [x] 编写可复现脚本 artifacts/backend-business-pressure-20261008.py，静态/语法检查通过。
- [x] 完成日常/突发/180秒连续/恢复业务压测；保留大输入OOM与立即再提交429失败证据，核对原始数据。
- [x] README 写入业务方案、结果、资源口径与适用边界；成功表严格区分两个隔离实例。
- [x] 审阅新增差异、确认后端测试服务已退出；静态检查及相关回归 14 passed，4399/9919 端口已释放。
