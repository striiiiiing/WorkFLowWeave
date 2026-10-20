## Context

参见 [proposal.md](proposal.md) 了解动机。当前发布 wheel 由 Hatchling 直接从 `src/workflowweave` 打包；前端由独立的 Vite 项目构建，FastAPI 应用工厂注册 API 路由而不托管静态资源。CLI 已有以配置文件启动的 `start` 子命令，生命周期从配置构造服务。微信 bridge 位于可发现的渠道插件内。

## Goals / Non-Goals

**Goals:** 在 Python 构建生命周期内构建并打包前端资源；用单一应用工厂确定性地分发 API、静态文件和 SPA 路由；提供路径和监听配置清晰的免配置启动入口；保证运行期渠道依赖按实际启用时解析。

**Non-Goals:** 改变 Docker 部署拓扑、重做现有开发模式或改造其他渠道的可选依赖模型；在运行时下载/构建前端资源。

## Decisions

1. **使用项目内 Hatch 自定义构建钩子。** 发布 wheel 使用 Python >=3.12，构建环境提供 Node >=22 和 npm；钩子显式检查 Node 版本后在前端目录执行锁文件驱动的 `npm ci` 与生产构建，并通过 Hatch `force_include` 放入 `workflowweave/web_app`。同一钩子安装并打包微信 SDK 的生产依赖。editable 安装跳过 Web 构建；sdist 包含完整前端输入与锁文件，但排除 dist、node_modules 和缓存。运行期安装 wheel 不需要 Node/npm 构建工具。
2. **应用工厂装配 SPA 静态分发。** 静态资源挂载应在 API 路由之后，并明确区分 API 前缀、已存在静态文件、前端页面请求和未知资源；history 回退仅为页面导航返回入口，不把缺失 JS/CSS 或 API 请求变成 200 HTML。相较中间件级 catch-all，该路由方式保留 FastAPI 对 API 的错误语义和文档端点。
3. **将 `serve` 做成现有 `start` 的配置适配入口。** 解析命令参数和环境变量，准备用户数据目录及默认配置，再委托已有生命周期启动路径；保留 `start --config` 作为显式高级用法。监听默认值使用 loopback；路径由平台用户数据目录确定，避免把包安装位置或工作区当作可变状态目录。
4. **Node 解析集中在微信插件共享边界。** `nodejs-wheel-binaries` 在支持的 x86_64 平台作为主依赖自动安装，免去用户额外指定安装项；ARM64 运行微信 bridge 需要系统 Node。优先已安装的包内 Node，其次系统 node；显式 command 保持优先。登录和 bridge 复用同一解析函数，缺少 Node 时明确报渠道错误。主服务只做可用性诊断并记录 warning，不启动 bridge，不影响其他能力。
5. **发布保留独立且可核实的验收项。** 构建 sdist、wheel，执行 twine check、干净安装与 HTTP 冒烟后，通过 GitHub Release 触发 PyPI Trusted Publishing。Release 由维护者明确创建；完成本地验收不代表已经发布。

## Risks / Trade-offs

- [前端构建工具与 Hatch hook 生命周期不兼容] → 在干净源码包上运行 wheel 构建，并检查 wheel 内容及安装后资源可读取性。
- [路径回退掩盖 API/静态文件错误] → 明确拒绝 API 前缀和静态资源扩展名的 SPA fallback，并分别覆盖深层链接、API 404 和资源 404 场景。
- [用户数据目录在不同操作系统行为不同] → 使用平台惯例的数据目录库并允许显式路径覆盖；测试覆盖配置优先级和默认路径。
- [Node wheel 没有 ARM64 发行物] → ARM64 不在随包 Node 支持范围内；微信启用时使用系统 Node，其他能力保持可用。
- [依赖标记无法表达 glibc/macOS 最低版本] → 受支持的 x86_64 目标系统满足 Node wheel 标注的系统基线；其他 x86_64 系统可按安装错误改用系统 Node并调整依赖策略。

## Migration Plan

1. 先实现并验证包构建、托管和 CLI；已有源码开发、Docker、`start --config` 路径继续运行。
2. 在干净环境构建 wheel、安装至隔离环境并验证 `serve`、静态资源、API 和微信渠道解析行为。
3. 发布新版本时通过版本化 wheel 提供新入口；回滚通过安装前一版本完成，不迁移现有显式配置目录。
