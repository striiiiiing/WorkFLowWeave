# 业务工作流示例与默认格式选择

依据 2026-10-07 用户最新要求；用户授权先更新设计后直接实现、异步审查。README 移除公开数据集评测交付要求，引用论文解释场景动机，历史研究归档保留。三个例子必须通过本项目执行、保存运行/Agent 历史，并通过已有 QQ 渠道通知；最终服务器部署待用户选好机器。

## 场景契约

1. **LLMs as a lossy compressor：新闻研判（新闻源可替换为日志等信息）**。新闻 MCP 采集多条有正文或充分摘要、日期和来源 URL 的新闻；较弱 Luna LLM 按业务目标保留事实、数字、时间、冲突和出处，压缩为交接材料；较强 Sol LLM 基于摘要给出业务总结。后者仅收到 compress 输出：fan-in order=[compress]，不含 $input，single_task_optimization=false。不得把只有标题的来源说成丰富正文。
2. **股票分析 fan-out / fan-in**。较弱 Luna Agents 按经营财务、估值行情、风险事件三个固定方向使用已绑定的搜索 MCP 检索分析；提示词明确要求实际调用 MCP、注明查询日期和证据 URL。较强 Sol LLM 汇总共识、分歧与证据缺口。价格、估值和财报必须区分时点及口径。Agent MCP 来自实际采集源绑定，不只写在提示词里。
3. **GitHub 新 issue 任务分工（无 fan-in）**。追踪一个明确仓库和 issue，MCP 同时采集 issue 与 README。任务数组第一项为较强 Sol LLM，根据 README 描述的用户、核心功能和业务边界判断严重度与修理必要性；第二项为较弱 Luna Agent，使用 GitHub 官方 MCP 查询代码、评论和关联 PR，调查根因、区分证据与假设。fan_in=null；两项独立输出，业务判定不得冒充已经验证的技术根因。首次示例手动选择现存真实 issue，不声称已部署 webhook/轮询监听。

## 接入、模型和交付

模型复用 inspection_ai 的实际 Luna/Sol 标识，全部走项目 LangChain/LangGraph 和流式接口；Sol medium、Luna xhigh。若接入方不支持参数，明确报告错误，不静默换模型或删参数。手动触发、retries=0，不自动启用 schedule，不扩张旧评测。MCP 固定可复现版本，环境变量提供凭据；GitHub 官方 MCP 只读。

示例引用部署者已有 QQ 渠道，通过 CLI 导入并运行；公开资源不含个人 channel ID、目标 ID、密钥、密码和私有 API 地址。实际测试配置留本地权限受限目录，可替换已有 AI/QQ 资源引用，不复制明文秘密进公开示例。

每个示例完成后制作非 Git 文件备份，存放工作区外权限 0700 的目录，归档文件 0600，保存 SHA-256 和文件清单；备份覆盖示例、对应 spec 与测试证据。私人接入配置若需备份仅进入权限受限备份，不进入 Git，不打印秘密。严禁以 git commit 代替备份。

## README 与前端

README 说明三种场景及论文适用边界，不将作者训练/问题相关压缩结果冒充本项目盲压实验，未统计完整费用不得声称已验证节费或提质。输入格式默认显示：none（原始 JSON/文本）、ISON、TOON、ZON、Markdown、CSV；按实际实现注明可用结构与严格往返检查，格式转换与 LLM 有损压缩分开。其余高级选项不变。

## 验收

先配置/schema/拓扑测试，再真实 MCP list_tools 与调用，再项目真实工作流及 QQ 发送；保留 session ID、Agent 工具调用证据、输出、usage 与通知状态。失败阶段如实记录，不用 mock 冒充通过；费用未知不视为免费。前端定向组件测试、typecheck/build、最小页面烟测。交付状态明确区分本轮示例测试与之后新服务器部署实测。
