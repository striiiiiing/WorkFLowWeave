# LogAgent 前端

Vue 3 Composition API + TypeScript + Element Plus + Vue Router + Vite。保留蓝灰配色、桌面侧栏、移动抽屉、明暗主题和纵向工作流卡片。

## 开发

需要同时运行后端和前端。先在仓库根目录启动真实后端（首次生成配置，已有配置不要覆盖）：

```sh
uv sync --group dev
uv run logagent config-example --output config.json
uv run logagent start --config config.json
```

默认后端地址为 `http://127.0.0.1:4300`；配置、数据库与密钥保留在本地，不纳入 Git。另开终端启动前端：

```sh
cd frontend
npm ci
npm run dev
```

开发地址默认 `http://localhost:3000`。`/api` 默认代理到 `http://127.0.0.1:4300`，与后端 `SystemConfig.port` 一致。使用自定义后端端口时，通过 `API_TARGET=http://127.0.0.1:8000 npm run dev` 显式指定目标；修改环境变量后重启 Vite。`npm run dev` 只启动前端，不会自动启动 Python 服务。

启动后用 `curl -i http://127.0.0.1:3000/api/health` 检查完整代理链路，应返回 JSON 健康报告。若返回空的 HTTP 500，检查 Vite 终端的代理错误和目标后端端口；不要将这个响应当作后端 JSON 格式错误。健康报告也可能以 HTTP 503 返回 `unavailable`，应按组件诊断排查。

若在 WSL 的 Windows 挂载目录中修改文件后没有热更新，可用 `CHOKIDAR_USEPOLLING=1 npm run dev` 启用文件轮询；浏览器验收使用生产预览，避免开发依赖重新预构建引起页面重载。

## 代码组织

- `src/app/` 负责应用装配、注入 API 实例、路由、布局、导航和全局样式。
- `src/pages/` 保存懒加载路由页面与跨模块流程，例如从已加载的运行记录创建 Agent。
- `src/modules/{resources,workflows,runs,agents,system}/` 分别拥有业务 DTO、API、控制器和界面。其他模块和页面通过对应的 `public.ts` 使用模块能力；`workflows` 可以依赖公开的 `resources` 契约。
- `src/shared/` 保存 Axios 传输、异步请求生命周期、Schema 控件、共享类型和基础界面，不依赖业务模块。

页面组合控制器与模块界面，不重复实现模块请求或业务规则。每份查询状态和编辑草稿只有一个拥有者；`src/app/bootstrap.ts` 装配并注入模块 API。路由页面均懒加载。`/agents` 与 `/agents/:sessionId` 共用稳定的页面实例；离开 Agent 路由时释放会话状态。

旧 `views/components/api/composables/domain/adapters/types` 目录及 Demo 已清除；测试直接使用正式页面和模块。架构检查拒绝重新引入这些目录或导入旧路径，路由也没有过渡豁免。`/collector-demo` 保留到正式工作流页的重定向。

## 接口与行为

以 `src/logagent/interaction/routers.py` 和 `models.py` 为准：资源路径为 `/api/{kind}`，运行路径为 `/api/sessions`。资源类型为 `sources`、`mcp_servers`、`ai`、`channels`、`workflows`；没有独立凭据 CRUD 接口。来源编辑支持 MCP 目录 schema 驱动的参数、CLI argv/shell 调用和局部 token 限额。

后端目前内置 AI API 格式为 `OpenAI Compatible API`（provider 值 `openai_compatible_api`），需要有效的 `base_url`。插件参数与模型参数使用带语法校验的 JSON 对象编辑器；参数业务约束由后端验证，插件页可查 Schema。

运行轮询间隔 2 秒，在请求完成后计时，终态和错误都会停止轮询；错误可手动刷新重试。页面销毁会取消请求。阶段内容总是携带明确版本，不跨版本缓存正文。取消响应不会直接伪造本地终态。

## 验证

```sh
npm test
npm run typecheck
npm run architecture:check
npm run format:check
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

浏览器测试需要根目录已有 `.venv` 及后端依赖，会使用临时目录启动真实 FastAPI（14300）和生产预览（13000），不会修改项目运行数据。通过内置离线采集器验证运行与阶段读取，不调用外部 AI 服务。单元测试覆盖 HTTP 契约、请求竞态、作用域清理、轮询和 JSON 表单校验。

实际环境需另外运行 `npm run test:live`：此检查不启动测试服务器，直接访问当前运行的 `http://127.0.0.1:3000`（可用 `LOGAGENT_FRONTEND_URL` 指定）。验证健康报告、资源/运行/插件列表、页面接收和资源保存；只创建带唯一 ID 的临时采集源，结束时删除，不触发工作流。后端未启动或代理不通会直接失败。隔离测试通过不能替代这项检查。

过渡代码清理的依据与验证记录见 [OpenSpec 清理任务](../openspec/changes/archive/refactor-frontend-architecture/tasks/2026-10-05-transition-cleanup/task.md)；既有 `proposal.md` 与 `design.md` 未改动。

资源文件使用 v4 格式。旧 Collector/Setter 来源不会自动迁移；需要显式创建 MCP 服务及其工具来源，或 CLI 来源。工作流选择资源实例，并单独配置输入格式与 token 限额；AI 配置需要真实模型服务。

前端使用顺序：进入“资源管理”查看默认数据源/渠道并添加 AI 配置，再进入“工作流管理 → 新建工作流”，选择数据源、分析任务的 AI/模型及通知渠道，保存后可编辑、立即运行或删除；运行详情中查看阶段结果。
