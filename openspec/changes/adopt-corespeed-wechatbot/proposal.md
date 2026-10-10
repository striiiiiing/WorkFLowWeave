# 改用 corespeed-io/wechatbot

## Why

2026-10-07 用户将微信依赖改定为 https://github.com/corespeed-io/wechatbot ，要求去掉前端风险提示，在 README.md 注明使用该项目。它替代此前的完整 OpenClaw 宿主方案及尚未完成的 WeClawBot-API 迁移。

## What Changes

- 固定使用该项目的 @wechatbot/wechatbot@2.2.0 Node SDK；npm 元数据表明无运行时依赖，解包 275,782 字节，不安装完整 OpenClaw。
- 保留初始需求：网页直接展示二维码/链接、数字确认、取消/刷新，凭据自动保存本地；通知和 Agent 双向对话。
- 去掉前端第三方风险警示，保留登录操作说明及每个 context_token 最多 10 条回复的平台事实。
- README 明确归属与项目链接，部署文档改为 SDK 的真实安装和状态路径。
- 后续自有实现仍记录用户提供的 https://cloud.tencent.com/developer/article/2651968 ，本轮不猜测尚未读取的文章正文。

## Evidence

源码核对 commit 6914de4e4cae966b1a3f4c6531711c9dffd84fee，Node 包 2.2.0。

- Authenticator.login 提供 onQrUrl/onScanned/onExpired/onVerifyCode 异步回调，等待 FileStorage 保存后返回。
- SDK 自带 HttpClient/ILinkApi/MessageParser/ContextStore/MessageSender/FileStorage。
- 高层 MessagePoller 提前持久化游标，且事件回调不等待 Manager 受理；不直接使用高层自动轮询，复用 SDK 的协议/解析/存储模块，由现有 bridge 在 Manager 确认后推进游标。
- HttpClient 默认网络超时重试两次，桥接显式设置 maxRetries=0，避免投递不确定时重发。
- SDK Python 版本回调/持久化能力与 Node 版本不同；Node 版本零 SDK 运行时依赖且有异步数字确认，更符合本次既有 bridge/网页要求。
