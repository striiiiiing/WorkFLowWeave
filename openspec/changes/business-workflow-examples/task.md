# 实施任务

> 此清单为早期方案历史，已由 2026-10-07 新需求取代。当前实现与审查参照 design.md 和 tasks/2026-10-07-news-stock-issue.md；不继续 PostgreSQL/FastAPI 示例。

- [ ] README 改为三个业务场景与论文引用，去除数据集评测交付要求，保留历史归档。
- [ ] 核验 Fetch / GitHub 官方 MCP 工具和参数，固定示例所用版本/来源记录。
- [ ] 提供 PostgreSQL 有损压缩、FastAPI/Pydantic Agent 调查汇总、GitHub issue 混合模型无汇总三个可导入示例，配置与操作文档完整。
- [ ] 实际 MCP 来源烟测、配置/schema/拓扑验证；不运行付费模型和不部署生产。
- [ ] 默认显示输入格式 selector，README 说明原始 JSON、ISON/TOON/ZON/Markdown/CSV 的用途和限制。
- [ ] 前端定向组件检查 → 类型/架构 → build → 最小页面烟测；审查改动并记录证据。
- [ ] 用户提供服务器后部署实测（本轮不执行）。

选择依据：官方 Fetch 将网页转 Markdown；GitHub 官方 MCP 支持 release、issue、评论和文件查询，能形成有引用的真实调查，而无需构造假数据。示例手动触发、retries=0，避免导入后自动产生费用。模型总时限900s沿用前期长推理联调配置，不据此保证所有请求必然成功。JSON 输入预算为空防止未知模型 tokenizer 导致演示无法运行，不使用字符估算。
