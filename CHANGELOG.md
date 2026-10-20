# 版本变化

## 0.1.2

- 增加可从 Python wheel 安装并通过 `workflowweave serve` 启动的 Web 应用。
- 增加通过 GitHub Actions OIDC Trusted Publishing 发布到 PyPI 的流程。
- 微信 Node bridge 运行时随 wheel 分发，x86_64 平台自动安装 Node；ARM64 使用系统 Node。
- 最低 Python 版本提升至 3.12，与正式构建环境和 CI 测试矩阵保持一致。

## 0.1.1

- 后端和 CLI 默认端口统一为 `4333`，前端默认访问端口改为 `3332`；Docker、代理、检查脚本和文档同步更新。
- 修复前端提示词保存测试中的无效数据；普通后端测试不再依赖本机模型服务或用户 `.env`。
- 增加 GitHub 自动质量检查，测试、静态检查、构建和 Docker 启动检查通过后才发布镜像。
- Docker 镜像增加版本号和提交编号标签，方便固定版本和回退。
- 补充中文贡献说明、安全说明和升级提醒。当前仍面向个人单用户，登录鉴权后续加入。

**升级提醒**：旧的 `config.json` 请把 `port` 改为 `4333`；旧 `.env` 中的 `FRONTEND_PORT` 改为 `3332`，然后重启服务或重新创建容器。已有配置不会自动改写。

## 0.1.0

- 首个带版本标签的版本，提供工作流、Agent、多渠道集成和 Docker 部署。
- 提供前后端合一的 Docker 镜像。
