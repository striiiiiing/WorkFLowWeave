# 实施任务

2026-10-07 此实施被用户最新指定的 [corespeed/wechatbot 接入](../adopt-corespeed-wechatbot/tasks.md) 替代；保留为决策记录，未发布或部署。

依据 [proposal.md](proposal.md)、[design.md](design.md) 和上游 commit c8851d44f4c31ea814357308f2cf438ca5e588f5。用户要求改用指定第三方并前端提示风险；当前公开能力与既有网页登录/对话需求不一致，已提出明确选择，本轮默认采用现有通知 API，不扩展上游服务。

- [x] 1.1 记录 851 MB 依赖问题、上游真实接口与后续腾讯云文章链接。
- [ ] 2.1 HTTP 通知 adapter、凭据引用和显式失败/不确定回执。
- [ ] 2.2 前端风险及部署/终端扫码说明；移除无上游支持的网页登录与 Agent 能力。
- [ ] 2.3 删除旧 Node SDK/bridge 和无消费者登录基础设施；更新 Docker 和部署文档。
- [ ] 3.1 后端协议/注册回归、前端定向测试、静态检查/构建、浏览器 smoke。
- [ ] 3.2 OpenSpec strict、差异审查与验证记录。

## 决策依据

- API/path/认证/code=200：上游 README/main.go:startAPIServer；目标 ilink_user_id/context_token 来源于 auth.json，不提供任意接收目标。
- 保留 wechat_openclaw 名称仅为资源引用稳定；配置契约改变不伪装兼容，原配置在 schema 校验处明确失败。
- 本轮不继续 SDK 打包实验：用户已指定采用第三方独立 API 服务。
- 腾讯云文章请求得到防护页面，先记录链接与未来方向，不猜测内容。

## 验证记录

待完成后记录。
