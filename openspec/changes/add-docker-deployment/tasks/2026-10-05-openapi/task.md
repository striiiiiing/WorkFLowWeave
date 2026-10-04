# 部署验收：修复原有 OpenAPI 生成失败

依据：design.md「启动验收发现的契约修正」。实际容器 GET /openapi.json 返回 422，错误定位到 SourceConfig.call.discriminator.mapping.cli.string_type；git show ee5dc80:src/logagent/models.py 证明嵌套 discriminator 在基础分支已存在。

- [x] 删除 SourceCall 冗余外层 discriminator，保留严格模型与 CLI 的 mode 判别。
- [x] 加入真实 OpenAPI HTTP 回归，运行来源配置、MCP/CLI 相关测试（60 秒硬超时）。
- [x] 重建后端镜像，在 Nginx 代理下验证 OpenAPI、Web SSE、配置和会话重启恢复。

不需要数据迁移：JSON 字段和值未改变；修正的是类型选择和生成的 schema。
