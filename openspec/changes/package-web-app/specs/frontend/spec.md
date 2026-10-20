## ADDED Requirements

### Requirement: 从 Python 服务访问前端

前端 SHALL 支持通过安装后的同一 Python 服务加载生产资源、请求 API，并在浏览器刷新 history 深层链接后继续显示对应页面。

#### Scenario: 浏览器直接打开深层链接

- **WHEN** 用户从已安装服务地址直接打开或刷新 `/agents/<sessionId>` 等前端路由
- **THEN** 浏览器加载 Vue 应用并交由 Vue Router 显示对应页面
- **AND** 前端通过同源 `/api` 地址访问后端，无需 Vite 开发服务器
