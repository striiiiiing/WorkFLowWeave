# 三个业务例子实测记录

2026-10-07 在 myserver 的独立测试实例执行，未替换现有生产服务。全部通过项目 CLI 触发，使用项目 MCP、LangChain/LangGraph、流式模型调用、阶段存档和 Agent 历史，QQ 使用已有机器人默认收件人。此次验证流程和输出边界；没有直读基线或质量标注，不能宣称已经证明净节费、提质或“定制优于通用”。

## 完整成功的运行

| 例子 | Session | 时长 | 验收证据 | AxonHub 已记录费用 |
| --- | --- | --- | --- | ---: |
| 新闻有损压缩（新闻源可替换为日志等信息） | `fca3c972541f4dbaa979de37b141e728` | 103.7 秒 | Fetch RSS → Luna → Sol；QQ final 成功 | 0.0129775 |
| NVDA 股票 fan-out / fan-in | `5e408886d92c40e690cc4553b444efd6` | 598.1 秒 | 三路 Agent 均成功，实际搜索和财务/行情调用；Sol 汇总；QQ final 成功 | 0.04446270 |
| GitHub issue 分工，无 fan-in | `bf12638836b84002bacce3d5c2bfbadc` | 126.3 秒 | issue + README 全文；Sol 业务定级在前，Luna 根因 Agent 在后；两个输出分别 QQ 成功 | 0.01873240 |

三次成功运行费用合计 **0.07617260**。表中是 AxonHub `usage_logs.total_cost` 原始计费单位，币种未独立核实。模型为 `gpt-6-luna` xhigh、`gpt-6.1-sol` medium，所有账单请求 `stream=1`；部署使用 inspection_ai 路由和用户指定的服务端凭据，公开例子不含凭据。

### 新闻

Fetch MCP `mcp-server-fetch==2026.8.18` 实际读取 BBC World RSS，多条标题、摘要、日期及 URL，**未阅读全文**。Codex 交接 prompt 加入跨境数字内容/订阅业务的监管、版权、消费、服务中断保留优先级。Luna 保留了年龄验证、内容交易等候选事实及不确定性，Sol 生成条件式业务简报。

实际下载的 o200k_base 计数：来源共享输入 **4963 tokens**，压缩摘要 **759 tokens**，约 **6.54x**。Sol 服务商报告输入 **877 tokens**，包含汇总提示和消息开销；Luna 输入 5553、输出 3392，其中 reasoning 2627，不能只按可见摘要计算压缩费用。Fan-in 仅 `order=[compress]`，禁用单任务优化，没有 `$input`；实现会在分析后清除不再需要的共享原文。账单请求 207096（Luna）、207101（Sol）。

模型仍沿用交接摘要的“下一步”结构，未严格生成六张事实卡；RSS 和真实业务暴露信息均有覆盖限制。此例没有通用压缩 prompt 对照，不能作为定制提质证据。

### 股票

yfinance MCP `yfmcp==0.14.0` 的三个 Luna Agent 分别实际完成：经营财务的搜索、年度报表、Ticker 信息；估值行情的搜索、周频价格及分析师目标价；风险事件的搜索。三个方向串行执行，fan-out 指职责拆分。工具历史和完整回包保存在项目 Agent 存档中。

Sol 区分了年度财务、周频行情和无统计日期的目标价，并指出财年末日期、币种、净利润增速和新闻链接的不一致。搜索只有标题及元数据，可能混入其他股票的文章；部分 Agent 报道链接发生不一致，汇总已列为复核项，**没有把全部引用 URL 验证为有效网页**。这份例子验证研究分工和证据汇总，不是可直接据以交易的核验报告。`yfinance_get_ticker_news` 曾返回 NO_DATA，已明确改用经真实调用可用的 `yfinance_search`。

### GitHub

GitHub 官方 MCP v2.0.0，只读 stdio，实际对象为 `pallets/flask` issue **#6146**：是否在 Hosting Platforms 文档加入 Cloudflare 链接。采集的 README commit 为 `d73fa1cdcbd8b1465c151db8924ba58b1dd14e35`；动态选择最新开放 issue 不是 webhook 监听。

Sol 根据 README 判断为低严重度的文档需求。Luna 实际调用 `issue_read(get_comments)` 和 `get_file_contents(docs/deploying/index.rst)`，确认当前平台清单未列 Cloudflare，评论没有关联 PR；明确没有运行时故障证据，未编造代码 bug。业务 LLM 未收到根因 Agent 后续发现，两份输出独立保留。

## 失败与修复费用

| 轮次 | Session | 原因 / 结果 | 已记录费用 |
| --- | --- | --- | ---: |
| 新闻首次预检 | `bd49edd6520742c7b7dfe810024703d4` | 采集成功；未知 tokenizer 映射在模型调用前明确停止 | 没有模型调用 |
| 新闻旧 prompt | `1a277eb286a2424d8ecd5037831649a6` | 链路成功，但摘要过长，后续重做 | 0.0243200 |
| 股票首次 | `83c417bd9bb74c22910821240d77e4f7` | 未启用 read，长 MCP 结果无法读取；取消 | 0.01189360 |
| 股票第二轮 | `0dc823c28a38479fbefb0471388ee2df` | 单行 JSON 超过预览预算；取消 | 0.00820156 |
| GitHub 首次 | `20af90909c814e688dd9db70e3ffae21` | 业务输出成功，重复目录/README 查询使 Agent 耗尽默认图步数，partial | 0.01760052 |

加上成功轮，本次所有上述试跑已记录费用总计 **0.13818828**。取消请求 **207086、207177** 缺失 usage，费用未知，未当作免费；因此该数是已记录合计，而非保证最终扣费总额。账单按凭据 ID 和 session UTC 时间范围关联，旧请求正文已被清理，不用空正文推断是否包含原文。

修复包括显式本地 tokenizer 映射（gpt-4o 对应真实 o200k_base，不发送上游）、支持 GitHub MCP 的嵌入文本资源并保留 URI、Agent 启用 mcp + read，以及删除 GitHub 重复调查。隔离实例 Agent 使用 preview_tokens=16000、output_tokens=16384、read_concurrency=1；图递归限制和项目全局默认没有提高。输入限额是真 tokenizer 计数，工具预览预算仍采用框架计量，两者不能混称。

## 验证和备份

定向后端测试、Ruff、前端 8 项组件测试、typecheck 与 build 通过。真实 Tabbit 页面确认普通模式的六个格式选项可操作；390x844 视口无横向溢出。截图：[桌面](../artifacts/business-format-desktop.png)、[手机](../artifacts/business-format-mobile.png)。

运行原始证据留在服务器隔离实例 `evidence/`，含阶段结果、Agent 工具事件、usage 账单；QQ 私人信息不会复制到公开文档。每个完成项在服务器 `~/.workflowweave-backups/business-examples/` 做独立文件归档，目录 0700、文件 0600，并提供文件清单和 SHA-256 校验；没有 Git commit。最终更新另做合并归档，完整路径见同一 change 的 tasks 记录。

用户选择新服务器后的部署实测尚未开始。可导入资源、实例设置和逐个运行说明见 [示例目录](../examples/workflows/business-scenarios/README.md)。
