# 新闻、股票与 GitHub issue 示例实施

依据：本 change 的 design.md；2026-10-07 用户要求三个例子实测、使用 QQ、强业务 LLM 前置而弱根因 Agent 后置，每完成一项进行非 Git 备份。

- [x] 更新设计；保留旧 task.md 为历史，新增本实施记录。
- [x] 核验三个 MCP 固定版本及真实调用；本地安装超时后在隔离服务器使用已缓存依赖验证成功，保留网络失败记录。
- [x] 准备新闻配置/拓扑测试；端到端验收另列下方。
- [x] 准备股票三方向配置/拓扑测试；端到端验收另列下方。
- [x] 准备 GitHub 双输入与任务顺序配置/拓扑测试；端到端验收另列下方。
- [x] README 移除数据集/judge 交付要求，说明论文边界、三场景、格式转换选项及导入运行。
- [x] 默认显示格式 selector；组件测试（8 passed）→ typecheck → build（通过；仅第三方注释警告）。
- [x] 扫描 diff 与公开文件秘密；记录实际验证及限制。

实现选择与默认值：手动触发和 retries=0 避免导入触发付费或重复费用；模型复用 inspection_ai，Sol medium / Luna xhigh 来自用户此前参数要求。模型 timeout=900s 沿用已联调长推理配置；来源 timeout=120s 给 stdio 首次启动与联网留余量；不以字符估算 token。压缩预算通过 max_tokens 参数，不在 prompt 硬写 token 数；Agent 步数与新闻篇数在工具核验后写入本记录并注明覆盖限制。备份使用用户要求的文件归档及校验，不做 Git commit。


## 联调修正（2026-10-07）

- QQ 复用 myserver 已有 qwenpaw_qqsend，机器人已捕获用户收件人；不修改另一个 SDK QQ 渠道。公开例子只使用 business_qq 资源引用，私人目标由渠道承担。实际 QQ 插件发送已取得有效回执。
- 试运行 bd49edd6520742c7b7dfe810024703d4：Fetch 采集成功；input_processing 在付费前因 gpt-6-luna 路由无 tokenizer 映射而明确停止。新添本地模型选项 tiktoken_model_name=gpt-4o（tiktoken 映射到 o200k_base，与旧评测相同）。AIService 输入计数与 ChatOpenAI 共用配置，选项只用于本地、不发给服务商；未知映射仍失败，不估算。依据 src/workflowweave/ai/service.py 与 evals/run_longmemeval.py TOKENIZER_NAME。
- 模型显式 streaming=true；Luna max_tokens=16384 包含 xhigh 的思考输出，不是摘要长度目标；摘要 prompt 需限定业务交接长度。
- yfinance_get_ticker_news 返回 JSON NO_DATA 却 isError=false；改为明确选用经实测可用的 yfinance_search，不做静默 fallback。每个股票 Agent 必须搜索，再读取其方向的数据；最多 5 次业务查询是示例调用预算，不是 runtime 强制限额。
- 真实端到端测试/QQ/逐项完成备份仍在进行。上方勾选仅表示配置准备完成，不能代表端到端验收已通过；下方新增验收清单为当前状态。

### 端到端验收（必须完成）
- [x] 新闻完整模型链 + QQ + session证据 + 逐项备份（fca3c972541f4dbaa979de37b141e728）
- [x] 股票三路工具历史 + Sol汇总 + QQ + 逐项备份（5e408886d92c40e690cc4553b444efd6，三路 success；213324-stock-verified 归档校验通过）
- [x] GitHub双输入 + 强LLM/弱Agent + 无汇总 + QQ + 逐项备份（bf12638836b84002bacce3d5c2bfbadc，214232-github-verified 归档校验通过）
- [x] README/操作文档与实际验证一致；docs/business-scenarios-validation-20261007.md 明确成功、失败、费用与限制。

### MCP 文本资源修正

依据真实 GitHub MCP v2.0.0 的 get_file_contents 回包：README 位于 content[].type=resource 的 resource.text，text 块只有下载状态。修复共享输入提取层支持嵌入文本资源，保留 resource.uri 作为出处；二进制 blob、图片和无文本的资源仍明确报 input_content_unsupported，不能静默跳过。先以回包结构写回归测试，再实现，再验证实际共享输入包含 Flask README 正文。此修正落实 design 的双输入契约，不改变设计。

股票首轮因 agent_tools 只有 mcp 而无法读取长结果 artifact，导致重复查询并耗尽图步数；改为 mcp + read，提示串行工具与分页，不增大 recursion_limit。新版 session 0dc823c28a38479fbefb0471388ee2df 正在验证。风险分支重复搜索指令需去重。

复测 0dc823c28a38479fbefb0471388ee2df 已取消：工具正文为单行转义 JSON，read 的整行分页无法容纳在默认 2000-token 预览中（next_offset 停在 15）。保持原始产物与分页契约，使用已有 Agent preview_tokens 配置在隔离实例显式设为 16000，以容纳本例搜索/财务完整回包；依据保存的真实工具历史，不更改项目全局默认与图步数。Agent output_tokens=16384，与 Luna xhigh 生成预算保持一致；read_concurrency=1 与用户串行调用要求一致。部署说明必须包含这些设置及作用范围，不能只导入工作流漏掉运行预算。

新闻新版：o200k_base 原文 4963 tokens，摘要 759 tokens（6.54x）；Sol provider input 877 tokens。AxonHub 两次调用 total_cost 合计 0.0129775（账本单位，尚未核实币种）。这只是运行数据，没有全文直读基线，不能据此声称质量提升或净节费。备份位于服务器 ~/.workflowweave-backups/business-examples/20261007-211656-news-v2。

GitHub 首轮 20af90909c814e688dd9db70e3ffae21：README 正文已进入共享输入、业务 LLM 成功，根因 Agent 在 read self / list / 两次 describe / 评论 / 重读 README 后触及 LangGraph 默认 25 步，结果 partial，不能验收。去除重复读取已提供 README 及工具目录的提示依赖；已验证官方工具参数的调用直接执行，最多四个业务查询用于评论和涉及文件。该例删减冗余查询，不提高图步数，不将 partial 记为完整成功。

前端验收：8 个组件测试、typecheck、build 通过；Tabbit 真实桌面和 390x844 手机视口验证普通模式六种格式可选，选中 ISON，手机 scrollWidth=375 <= viewport=390；截图 artifacts/business-format-{desktop,mobile}.png。初次浏览器页面续接和点击输入框遇异常，重新取得实际页面并点击可见选择控件后通过，没有强制点击或替代数据。

GitHub 第二轮：业务判断低严重度的文档增补；根因 Agent 实际调用 issue_read(get_comments) 和 get_file_contents(docs/deploying/index.rst)，确认缺少 Cloudflare 条目，没有编造运行时 bug。两项结果分别 QQ 发送成功，fan_in=null，没有额外模型汇总。相较首轮去除冗余调查后完整成功，费用 ledger total_cost=0.0187324。最终共享输入包含完整 README 文本和 issue，相关证据在服务器 evidence/github；失败记录保留在 evidence/github-failed-v1。

最终验收：后端 54 passed（timeout 60s），Ruff、diff whitespace 检查通过；前端 8 passed、typecheck/build 通过，桌面/手机真实烟测通过。三成功轮已记录费用合计 0.07617260，包含旧 prompt、失败及取消轮的已记录合计 0.13818828；取消请求 207086、207177 无 usage，费用未知不当免费。完整明细与输出边界在 docs/business-scenarios-validation-20261007.md。

逐项备份在 myserver ~/.workflowweave-backups/business-examples/：20261007-211656-news-v2、20261007-213324-stock-verified、20261007-214232-github-verified。GitHub 归档同时保留私人资源和 QQ 插件配置，目录权限 0700、归档权限 0600；文件清单和 SHA256SUMS 校验通过。另制作最终交付归档与 SQLite 一致性快照，不做 Git commit。新服务器部署尚未开始，Tavily 按用户要求暂停。
