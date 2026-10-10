# README 成本与效果：真实上游账单 + LLM judge

## 依据和范围

- 用户追加要求：先收尾当前演示，再优先找公开数据集；比较 ISON/ZON + token 过滤与按需求摘要后交强模型的流程；judge 用 GPT-6 Luna max，费用从上游获得。
- 当前真实截图、MCP 部署、巡检运行已验收；GitHub 仍缺 gh 认证，最低硬件仍等待用户租机，不宣称完成。
- 输入与错误前置顺序依据 collect-from-mcp-and-cli 的既有 proposal/spec；复用 `workflow/input_processing.py:process_input` 与 `AIService.input_counter`，不修改 proposal/design。
- 文件：`evals/` 的数据清单、生成器、runner、judge 提示词、上游费用读取和汇总；`tests/test_evaluation.py`；README / production-demo 验证记录。

## 2026-10-06 评测口径修订

以下决策 supersede 本文件中早先的 BGL、合成样例、token 裁剪和旧模型描述；proposal/design 不变：

- 用户明确选择 Kaggle `Synthetic Security Logs V1` 的两个固定 case；每 case 最新 100 条错误/失败在前，再接最新 100 条成功/其他记录。保留所有原始 CSV 列和值，点号列名用 `__` 可逆映射；100/100 只代表测试窗口，不能外推源文件故障率。
- 只跑六条路线：JSON/ZON/ISON，各自分为直接强分析和先弱摘要再强分析。字段长度、单条来源、总输入 token 限制全部关闭；字符数只做体积记录，真实 token 只读 AxonHub usage，不能事先按质量筛选字段。
- 弱摘要使用 `gpt-6-luna / low`，强分析使用 `gpt-6.1-sol / medium`，judge 使用 `gpt-6-luna / max`；不要使用 GPT-6 Sol 或旧 `gpt-5.6-sol`。上下文 105 万 token 是用户提供的实验配置假设，不冒充官方规格。
- 每条件每 case 一次生成；业务请求应为 12 次强分析 + 6 次摘要，共 18 次。每个非 JSON 基线条件与 `json_full` 做 AB/BA judge，共 20 次理论请求；失败请求保留失败且不按零成本计。
- 摘要 workflow 只有 `compress` 分析 task，fan-in 使用 GPT-6.1 Sol，`order=["compress"]`、`reuse_from=None`、`single_task_optimization=false`，避免把原始输入借优化路径重新带入强分析。当前 runner 的业务调用复用生产预处理并直接 HTTP，不能宣称实际执行了完整图编排。
- judge 提示词必须为六个维度提供 1/3/5 分锚点、逐项证据理由和 tie 规则，并接收完整 `selected_sources` 与 reference；格式名称、模型强弱和费用不得成为评分依据。
- LLM-as-a-Judge 口径依据 OpenAI 官方 Graders 文档（`https://developers.openai.com/api/docs/guides/graders`）：grader 比较 reference answer 与 model output，并允许可解释的部分分；本实现将 `reference_answer` 固定写入每个 case，再让 judge 按答案事实逐项评分，而不是只给抽象质量标签。

## 设计决策

- GitHub REST 成功获取 LogHub BGL 2k CSV 与 LICENSE。固定 commit `dd61d0952749ee7963bde24220d1be5ede023033`、blob `8ed3a917564276091890ba6f323e5284b09f0227` 和 SHA-256，按原顺序取两个400行窗口。BGL Label 只给 judge；不把系统日志级别伪造成 HTTP 最终状态。
- 仓库自建两个100请求样例，覆盖重试恢复、最终失败、取消、长错误和数据内指令。与公开日志分组报告，未发布前不声称其为外部公开基准。最低硬件无变更。
- 对照6条件：完整 JSON、裁剪 JSON、裁剪 ISON/ZON，以及两个格式的弱摘要→强分析。2,000/1,200/96 token 预算用于主动制造有限输入，不冒充推荐生产值；摘要2,048、分析4,096输出上限，按同任务匹配。
- 弱模型 gpt-5.6-luna low，强模型 gpt-5.6-sol medium；模型来自当前上游目录，实际计费模型单独记录。judge 固定 gpt-6-luna max，探针 request 202241 / response resp_017de0f5e6394acd016ac49dd1c580819b95a5b70d01d25206；上游请求 reasoning_effort=max，费用 $0.0000202，作为独立探针，不混入评测费。
- 4样例×6条件业务32请求；相对完整JSON基线每个优化条件交换位置两次 judge，共40请求。固定随机种子20261006打乱业务顺序；并发3减少长时间串行且限制上游压力，每请求300秒参考已有演示预算；不自动重试或换模型。
- 质量六维1–5，按同样例平均以免基线多次出现加权失衡；配对胜者需位置一致，否则记录冲突。样本小/无独立人工复核，不能推导统计显著优势。
- 费用通过真实 response id 精确关联远端 requests.external_id 与 usage_logs.request_id，只读固定参数化 SQL，不拿同时间段其他请求当费用。未关联账单明确 missing，judge 费与业务费分离。

## 真实预处理暴露的格式问题

字段裁剪产生以空格结尾的重复长字符串。zon-format 1.2.3 默认 dictionary compression 的解码器会去掉末尾空格，已有严格等价校验明确拒绝，造成 ZON 条件失败。这是共享序列化边界的根因问题，不修改数据绕过失败：统一用公开的 ZonEncoder(enable_dict_compression=False)，保留表格/差分编码和严格往返验证，关闭该有损优化；没有静默 JSON fallback、private hook 或第二套编解码器。新增重复尾随空格与实际限额回归。

官方 OpenAI 文档搜索/读取遇到连接问题与403，本任务不把未读到的文档当依据，不声称官方证明模型参数/定价；可调用性与max档以本次上游探针和数据库验证。

## 验收

- [x] 公开源、许可、固定哈希、字段隔离与两个仓库内确定性合成样例。
- [x] 实际生产格式/预算路径和无损ZON回归。
- [x] 4样例×6条件生成24份最终报告与8份摘要，32业务调用全部成功，保存实际输入/摘要/报告与响应ID。
- [x] 按response ID匹配32/32业务账单，实际合计$0.33953286；配置强模型映射到gpt-6.1-sol，缓存量与信息保留数随结果披露。
- [x] 40次max judge均保留失败：6次403、33次500、1次读取超时。失败来自本轮选用的上游渠道：同时间窗记录 INSUFFICIENT_BALANCE 和10请求/分钟（含失败）限制的429，后续路由出现500/超时；独立探针已验证 GPT-6 Luna max 可调用。评分、胜率、冲突率未验证，judge费用missing而非$0，整体partial。
- [x] 增加串行judge默认12秒起始间隔，以及--judge-only复用原业务响应/报告的新目录模式；回归确保不会重新调用业务模型或重复生成业务费。需先恢复上游余额/额度，已经用异步问题告知用户。
- [x] 评测与输入处理回归37 passed / 10.73s（60秒硬超时）；Ruff通过。在线构建因环境代理拒绝连接失败，显式使用本地依赖缓存的uv build --offline成功，无运行时fallback。
- [x] README、评测说明、成本记录与机器汇总/账本已更新；质量栏保留未验收。
- [ ] 上游额度恢复后仅重跑judge、导出其实际账单并完成分组评分。
- [x] 最终6份文档本地链接检查通过，production JSON证据可解析，diff --check通过；37份交付文件未包含实际API凭据。当前MCP/巡检回归复验15 passed / 44.90s。

## 当前矩阵状态

- [x] Kaggle 固定样本已生成并通过 SHA-256、JSON/ZON/ISON 严格往返检查；六条件输入均关闭长度限制。
- [x] 实际业务首轮已执行并保存失败记录；2 个 case 的 JSON/ZON/ISON 直分析均成功，摘要路线只有部分请求成功。已从 `myserver` 精确匹配 10/23 个首轮请求的 usage，未匹配项保留 missing。
- [x] judge 提示词已改为 Kaggle 口径，并为六个评分维度补充 1/3/5 锚点、证据要求和 tie 规则；完整 sources 在 judge-only 代码路径中传入。
- [ ] 六条件完整业务覆盖、20 次有效 judge、分组质量和总费用仍未完成；当前上游 403/500 失败不能支持“更便宜且更准确”的结论。
