# Docker 部署

## Why

用户要求合并通知渠道实现、推送 GitHub，并构建本地 Docker 镜像和提供启动方式；Docker Hub 上传不可用时保留以后上传的方法。

## What Changes

- 提供锁定依赖的后端与前端生产镜像、Compose 和启动文档。
- 持久化应用配置、SQLite、密钥、插件启停配置和微信登录状态。
- 验证实际启动，不引入新的业务运行时或预置 Collector。

## Impact

新增部署文件和文档；复用现有单进程后端及通知插件。
