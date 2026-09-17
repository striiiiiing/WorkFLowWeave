# LogAgent 前端模块 (Frontend Module)

本模块是 LogAgent 系统的 Web 交互视图层，采用 **Vue 3 + Tailwind CSS + Vite + Pinia + TypeScript** 构建，提供轻量、现代、零代码且手机端高度友好的交互界面。

详细设计规范与设计语言定义见：[前端模块设计文档](../openspec/changes/configurable-collection-analysis-workflow/modules/frontend/design.md)。

---

## 核心设计决策与索引映射

本项目代码中全面标注了设计语言决策索引，便于审查与校验：

| 决策编号 | 规范名称 | 实施位置与说明 |
| :--- | :--- | :--- |
| `DEC-TYPO-01` | 系统字体栈与 14px 基准字阶 | `src/assets/main.css`, `tailwind.config.js` |
| `DEC-TYPO-02` | 代码/ID 等宽字体与弱灰底色 | `src/components/common/Input.vue`, `src/types/index.ts` |
| `DEC-COLOR-01`| WCAG AAA 级状态徽标对比度 (≥ 7:1) | `src/components/common/Badge.vue`（深红/浅粉、深绿/浅绿、深天蓝/浅蓝） |
| `DEC-COLOR-02`| Slate 冷灰深浅双轨暗黑模式 | `src/components/layout/AppLayout.vue`, `src/components/common/Card.vue` |
| `DEC-LAYOUT-01`| 绝无画布，垂直阶梯流式编排 (Flow Stepper) | `src/views/WorkflowEditView.vue`, `src/components/workflow/*` |
| `DEC-LAYOUT-02`| 移动端全高抽屉导航与 44px 触控目标 | `src/components/layout/AppLayout.vue`, `src/components/common/Button.vue` |
| `DEC-ICON-01` | 对象、动作、状态图标三分类与无歧义 | `src/components/icons/AppIcon.vue` (恢复使用 `RotateCcw`，取消使用 `Stop`) |
| `DEC-ICON-02` | 1.75px 描边圆角线性与光学平衡对齐 | `src/components/icons/AppIcon.vue` (24x24 视框与不对称重心偏移校正) |
| `DEC-MOTION-01`| 150ms-250ms 微交互与减少动效适配 | `src/assets/main.css` (`prefers-reduced-motion`) |
| `DEC-SEC-01`  | 凭据前端只读脱敏掩码 | `src/views/ResourcesView.vue`, `src/api/client.ts` |

---

## 开发与构建

### 1. 安装依赖
```bash
cd frontend
npm install
# 或使用 pnpm / bun
pnpm install
```

### 2. 启动本地开发服务
```bash
npm run dev
```
开发服务启动于 `http://localhost:3000`，所有 `/api/*` 请求将自动通过 Vite 代理转发至后端 FastAPI 服务的 `http://127.0.0.1:8000`。

### 3. 类型检查与生产构建
```bash
npm run build
```
编译产物输出至 `frontend/dist`，可独立由 Nginx/Caddy 托管，或直接挂载至 FastAPI 静态路由提供访问。
