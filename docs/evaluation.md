# 成本、质量与验证边界

根 README 引用的压测采样口径、脚本和结果分别见 [部署测量](../artifacts/benchmarks/deployment/README.md)、[业务压测](../artifacts/benchmarks/business-pressure/README.md) 和 [只读 API 压测结果](../artifacts/benchmarks/deployment/api-pressure-20261008.json)。业务工作流模板见 [工作流示例](../examples/workflows/business-scenarios/README.md)。本页只记录这些模板的运行验证结果与适用限制。

## 2026-10-07：三个真实业务场景

在远端隔离实例通过项目 CLI、MCP、流式模型、阶段存档、Agent 历史和已有 QQ 通知渠道运行，未替换生产服务。使用 `gpt-6-luna` xhigh 和 `gpt-6.1-sol` medium。

| 场景 | 时长 | 已验证结果 | AxonHub 已记录费用 |
| --- | ---: | --- | ---: |
| 新闻有损压缩 | 103.7 秒 | RSS → Luna → Sol，QQ final 成功 | 0.0129775 |
| NVDA 多路调查与汇总 | 598.1 秒 | 三个 Agent 职责分支、真实工具调用、Sol 汇总、QQ final 成功 | 0.04446270 |
| GitHub issue 分工，无 fan-in | 126.3 秒 | README 与 issue 输入、独立业务与根因输出、两份 QQ 通知成功 | 0.01873240 |

成功轮费用合计 **0.07617260**，包含旧 prompt、失败和取消轮的已记录合计为 **0.13818828**。单位来自 `usage_logs.total_cost`，币种未独立核实；两条取消请求缺少 usage，费用未知，未计作免费。原始阶段、工具事件和账单保存在远端隔离实例，私人凭据与收件人不复制进公共仓库。

新闻共享输入 4,963 tokens，压缩摘要 759 tokens，约 6.54 倍；Sol 服务商报告输入 877 tokens，包含提示词与消息开销。Luna 输入 5,553、输出 3,392，其中 reasoning 为 2,627，不能只按可见摘要计算压缩费用。RSS 只提供标题和摘要，没有阅读全文；没有通用 prompt 对照，不能据此证明定制提质。

股票三个方向当次串行执行，fan-out 指职责拆分。数据的财年、日期、币种和链接存在待复核差异，部分搜索只含元数据，不能作为已核验的投资报告。GitHub 当次对象是 Flask #6146 的文档需求，动态选取最新开放 issue，不是 webhook，也没有运行时故障证据。

该轮验证流程和输出边界，缺少直读基线与质量标注，不能宣称已证明净节费、提质或定制优于通用。新服务器上的业务验证仍属于未完成任务。

## 压测适用范围

资源占用、并发压力、512 MiB cgroup 限额与只读 API 结果来自短时基准测试，用于复核 README 中披露的运行表现。它们不证明长期无泄漏，也不能与不同机器、负载或资源限制的实验混算。
