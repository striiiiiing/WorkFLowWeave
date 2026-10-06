# 插件数据源目录与编辑修复

依据：后端 `src/workflowweave/models.py` 的 `SourceConfig.one_execution_form` 允许且要求 `collector` 插件或 MCP/CLI `call` 二选一；远端 `/api/sources` 返回 23 条，`qwenpaw_hourly_flomo` 为 `collector=qwenpaw_flomo, call=null`。工作流绑定 ID 与目录一致。前端 `SourceSummary.vue` 读取 `source.call.kind` 抛错，导致 Vue 更新中断，后续资源误显示缺失，资源中心分类也无法完成渲染。本次按用户要求先修本地，再同步相同文件至远端，不改工作流数据或专门适配 QwenPaw。

## 决策

- 结构性修复前端 `SourceConfig` 契约：显式表示插件来源和 MCP/CLI 来源，摘要、搜索和编辑入口共同遵守此契约。保留后端作为来源类型的唯一判定处。
- 插件来源编辑保留 `collector`、`setters`、`template` 等已有字段，`options` 使用现有 JSON 表单组件编辑；插件选项的最终合法性由后端既有 schema 校验负责。不自动迁移或改写插件来源。
- 现有缺失态刷新动作可以保留作显式重试，但真实目录加载成功时不得把渲染异常误报为资源不存在。

## 验收

- [x] 单测覆盖 `call=null` 的显示、搜索和编辑保存（8 条定向测试通过）。
- [x] 前端类型检查与构建通过；本地浏览器连接远端 API 后显示 23 个来源、供应商列表及可打开的插件编辑器，缺失提示为 0。
- [x] 远端资源页及 `qwenpaw_hourly` 编辑页无浏览器异常：23 个资源、供应商渠道可见、缺失提示 0，插件来源可以打开编辑器。同步文件的本地与远端 SHA-256 一致。
