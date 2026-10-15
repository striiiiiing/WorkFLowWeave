# 项目目录结构

项目只保留一套 `data/` 运行时数据概念。`data-v4/`、临时状态目录和本地构建产物不属于当前版本；它们不会进入 GitHub，也不会复制进 Docker 镜像。

## GitHub 版本

下面是提交到 GitHub 的主要目录，省略了源码内部的普通模块文件：

```text
WorkFLowWeave/
├── .github/workflows/           # CI 与 GHCR 镜像发布
├── artifacts/                   # 可复核的公开验证证据与截图
│   ├── benchmarks/
│   ├── channels/
│   └── screenshots/
├── data/references/.gitkeep     # 文件引用目录占位；实际内容不入 Git
├── deploy/docker/               # Docker 入口与 Nginx 配置，随代码发布
├── docs/                        # 当前部署、架构、业务验证和目录说明
├── examples/workflows/          # 可导入的工作流示例
├── frontend/                    # Vue 前端源码、测试和构建配置
├── openspec/
│   ├── specs/                   # 当前有效行为契约
│   └── changes/archive/         # 已整理的历史设计，仅作追溯
├── plugins/.gitkeep             # 用户插件扩展入口，保持为空
├── src/workflowweave/           # Python 后端与内置插件
├── tests/                       # 后端测试与夹具
├── .dockerignore
├── .env.example
├── Dockerfile
├── compose.yaml
├── compose.backend.yaml
├── compose.build.yaml
├── compose.tools.yaml
├── LICENSE
├── README.md
├── pyproject.toml
├── uv.lock
└── package-lock.json
```

`deploy/docker/` 必须在 GitHub 中，因为 `Dockerfile` 会直接复制其中的 bootstrap 和 Nginx 配置。根目录 `plugins/` 只保留 `.gitkeep`，用户新增插件时把内容放入本地目录或 Docker 的 `user_plugins` 卷。

## 本地开发版本

本地会在 GitHub 目录之外产生依赖、缓存和运行数据：

```text
WorkFLowWeave/
├── data/
│   └── references/              # 文件引用；只有 .gitkeep 受版本控制
├── .venv/                       # uv/Python 虚拟环境
├── frontend/node_modules/       # npm 依赖
├── frontend/dist/               # 前端构建产物
├── artifacts/local/             # 本地截图、日志和临时验证结果
├── .pytest_cache/ .ruff_cache/  # 测试与 lint 缓存
└── .env                         # 本机部署参数，不提交
```

这些目录只服务当前机器，不与 `data-v4/` 并存，也不作为第二套应用数据源。删除本地运行数据时只需按实际需要清理 `data/`；Docker 部署的数据则由命名卷和 `REFERENCES_PATH` 管理。

## Docker 服务器版本

服务器 `~/opt/workflow/` 只需要代码仓库中的 Compose/Docker 文件和服务器自己的环境配置：

```text
~/opt/workflow/
├── .env                         # 服务器镜像、端口、代理和引用路径
├── compose*.yaml
├── Dockerfile                   # 仅源码构建时使用
├── deploy/docker/
├── docs/docker.md
├── data/references/             # REFERENCES_PATH 指向的宿主目录
└── plugins/                     # 可选的用户插件来源目录
```

运行时的配置、SQLite、主密钥、日志、微信状态和 HOME 在 `workflowweave_state` 卷；用户插件在独立的 `workflowweave_user_plugins` 卷。服务器不需要复制台式机的 `.env`、代理地址、虚拟环境、`node_modules` 或本地数据库。
