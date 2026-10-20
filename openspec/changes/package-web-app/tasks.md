## 1. Wheel 前端构建

- [x] 1.1 配置 Hatch 构建 hook 和锁定的前端依赖，构建 wheel 并验证前端生产资源包含在 Python 包内
- [x] 1.2 定义 x86_64 平台默认 Node.js 运行时依赖和 bridge 执行文件解析，验证未启用时不启动 bridge、缺少 Node 时服务继续运行、启用时解析正确或明确失败

## 2. 服务分发与命令

- [x] 2.1 在 FastAPI 应用工厂加入包内静态资源托管，验证根路径、history 深层链接、API 404 与静态资源 404
- [x] 2.2 实现免配置 `serve` 命令与数据目录、监听配置优先级，验证默认启动及参数/环境变量覆盖
- [x] 2.3 验证既有 `start --config` 和 API 行为保持兼容

## 3. 发布验收

- [x] 3.1 更新安装、serve 用法与 Node 构建前置条件文档，并验证说明与 CLI 一致
- [x] 3.2 完成全新依赖环境的 pip 安装与 Docker 构建验收（Python 3.12 新建 venv 安装本地 wheel 并启动 serve、请求健康接口通过；Docker backend 构建及容器健康接口通过）
- [ ] 3.3 合并 Trusted Publishing workflow 后创建版本 Release，通过 OIDC 上传 sdist 与 wheel，并验证 PyPI 页面和 pip 安装（等待维护者创建正式 Release）
