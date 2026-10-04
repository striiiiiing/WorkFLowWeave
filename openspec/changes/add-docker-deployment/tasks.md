# 实施与验证

依据：用户本轮部署授权、design.md；Python/SDK 依赖来源 pyproject.toml、uv.lock 和微信 package.json；端口和并发默认值来源 SystemConfig；停止宽限依据 lifecycle/service.py 分步清理预算。

- [x] 添加 Dockerfile、Compose、Nginx 和首次启动状态初始化。
- [x] 编写 Docker 启动、持久化、备份、微信登录和 Docker Hub 发布说明，更新 README。
- [x] 构建后端与前端镜像并实际启动验证健康、插件发现与状态恢复。
- [x] 验证 OpenSpec、相关静态检查并审查差异。
- [ ] 提交通知与部署改动，隔离合并并推送 GitHub。

## 实施依据与阶段证据

- 绑定和插件改动已提交为 b498db8；隔离集成分支基于刚 fetch 的 origin/refactor/frontend-architecture（ee5dc80），保留主工作区未提交文件。
- `tests/deploy` 的 4 项测试验证初次配置、重启保留、插件目录冲突和错误配置不覆盖；连同缓存/发现/迁移共 17 项通过（60 秒硬超时）。uv lock、Ruff、Compose config 和三项 OpenSpec strict 通过。
- Debian HTTP 下载连续无进展，改用官方 HTTPS 源并设置 30 秒连接/读取超时；不使用第三方依赖镜像。
- 运行工作目录选持久卷：固定 qq-botpy 的 logging.py 把默认文件 handler 路径绑定到 os.getcwd()；卷可写，应用代码目录保持镜像所有权，SDK 日志能随状态保留。
- 部署不会推送额外的 workflow SSH 服务器，只更新用户要求的 GitHub origin。
- uv 依赖安装与应用打包分层，并用 BuildKit cache mount 缓存下载；源代码变动不会重装锁定 SDK，UV_LINK_MODE=copy 避免缓存挂载与镜像层之间的跨文件系统硬链接。
