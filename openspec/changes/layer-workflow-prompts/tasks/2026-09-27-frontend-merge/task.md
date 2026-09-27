# 前端合并集成

依据：[提示词设计](../../design.md)、[提示词行为规范](../../specs/workflow-prompts/spec.md)、[调度设计](../../../unify-workflow-scheduling/design.md)、[调度行为规范](../../../unify-workflow-scheduling/specs/workflow-schedule/spec.md)及用户指出原合并遗漏前端功能。设计保持不变。

- [x] 在已合入两个后端分支的 `refactor/frontend-architecture` 基础上，合并 `implement/unify-workflow-scheduling-frontend-dfd61431` 与 `feature/layer-workflow-prompts-frontend`。
- [x] 默认值冲突保留每天 09:00 Cron 与共享提示词；基本信息组件同时保留计划预览及共享提示词。依据调度兼容规则，主动切换 Cron 模式清空时区，未修改计划时保留原时区。
- [x] 修正合并后测试：Cron 输入按 placeholder 定位，组件注入预览 API，分隔符按表单标签定位；新增提示词控件不能使原测试填写错误字段。
- [x] 隔离工作树验证：全量前端 232 项中 231 项通过，唯一失败测试修正后所在文件 3 项通过；类型检查、Prettier、架构检查与构建通过。后端计划/提示词/API 45 项、资源迁移 49 项通过，均以 `timeout 60s` 执行。两份 OpenSpec 严格校验通过。
- [ ] 在保留主工作区原未提交改动的前提下快进目标分支，验证合并后的实际工作区。
- [ ] GPT 6 Luna max 使用 Tabbit 验收真实临时后端的调度、提示词及保存重开，记录证据。

范围与依据：资源版本 3 由后端 `src/logagent/config/migrations.py` 按版本 1 调度迁移、版本 2 提示词迁移连续升级并原子发布；集成保留该机制。前端仍使用共享 `/api` 客户端，`frontend/vite.config.ts` 默认代理 `http://127.0.0.1:4300` 不变；验收服务通过临时环境变量配置隔离后端。
