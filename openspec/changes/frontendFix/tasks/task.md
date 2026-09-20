## 问题描述

- 定时间隔应当采用cron语法，而非是按间隔来（稍后修改，这个需要修改里头了）
- 前端的以下内容应该在高级模式才展开
  - 采集并发数
  - 包含采集数量 （默认应该为True）
  - 资源ID应该是非必选的，采用uuid来生成，高级模式才有手动填写选项
  - 分析并发数
  - 分析失败时的处理
  - 允许发送部分成功的结果
  - 持久化与备份
- 数据采集这个模块后为什么没有一个对结果进行排序的？
- 输入分隔符是什么？为什么前端没有提供采集器的几个选项？
- 插件参数应该采用填写参数的方式（拆分为Json的几种格式，只解析最外层的字段），而编辑json应该才是用户点击后才有的
- AI 配置为什么无法在前端设置凭证（要求有个眼睛图标，点击后才查看内容，否则为星星）


## 验收要求

修改以上内容，并且基于一般的AI实践，给出正常的方案


## 实施计划与根因（2026-09-20）

本次为跨表单与凭据入口的结构性修正，按现有设计落实，不修改 proposal.md / design.md。

- 根因：ResourceEditor 未读取 `/api/plugins` 的能力 Schema，采集器只能手填、options/setters 只提供 JSON；SourceStepCard 未渲染来源顺序调整和已有 source_overrides；高级选项没有统一的显示模式；AI 表单只支持 env/none，交互层没有接通既有 CredentialManager.protect。
- 影响文件：前端资源编辑器、工作流编辑器及阶段卡片、通用参数表单、资源 API、默认工厂；后端凭据 HTTP 投影与 WorkflowDefinition 默认值；对应单元与浏览器回归测试。
- 方案：新增统一的最外层 JSON 类型参数表单，Schema 直接来自注册能力；对象/数组只在字段值内编辑 JSON，完整 JSON 需用户显式切换。保留未填写字段的省略语义，不把 Schema 默认值批量写入配置，不吞掉非法输入。
- 排序依据：`modules/frontend/design.md §3.2` 要求来源顺序调整，Workflow 按 sources 顺序生成共享输入。因此新增上移/下移；单来源排序通过 Collector setters 暴露，不在前端另造跨来源记录排序。`collection/mock.py` 支持 sort_by/descending；`collection/logs.py` 明确保留文件顺序。
- 高级模式只控制显示，关闭后保留既有值；新资源和工作流采用浏览器标准 `crypto.randomUUID()`，高级模式可以手填或留空生成，后端 ID 校验保持权威。
- include_counts 新建默认值改为 True：直接依据本任务的明确要求，同步前端与后端，已保存的显式 False 保留。并发 4、AI timeout=600/retries=5、备份与失败策略保持现有模型默认，依据 `models.py` 和 `contracts/module-interfaces.md`，不凭经验另造时限。
- 凭据依据：`modules/config/design.md` 的加密存储约定与已实现 CredentialManager.protect。新增仅加密入口，浏览器本次输入使用密码框与眼睛按钮，资源保存使用密文；不新增已保存凭据解密回显，不把密钥写入日志或本地存储。加密失败明确阻止保存。
- 输入分隔符说明为“来源之间的正文连接符”，默认两个换行，依据 WorkflowDefinition.input_separator；不是单来源记录解析分隔符。
- Cron 按问题描述“稍后修改，这个需要修改里头了”暂缓，不把 cron 文本伪装成当前 interval_seconds。

## 验证计划

1. 参数表单类型、非法 JSON、模式切换、Schema 可选字段；资源 UUID、凭据加密失败与重试；排序和高级模式保值的针对性单元测试。
2. 后端凭据入口与 include_counts 相关回归（每次后端测试硬超时 60 秒）。
3. 前端类型检查、受影响文件格式检查与生产构建。
4. 使用独立临时数据目录运行 Playwright，验证真实 API 的创建/编辑、排序、凭据、移动端布局。

## 已落实与验证记录

- [x] 默认模式收起采集/分析并发、计数开关、分析失败策略、部分发送与备份；展开/收起不重置原值。
- [x] 新资源/工作流自动 UUID，高级模式允许自定义或留空自动生成。
- [x] 采集来源上移/下移；资源及工作流内按插件 Schema 展示参数/处理规则，来源内部排序只提供实际支持的 Setter。
- [x] 通用 ParameterField 支持最外层字符串、数字、布尔、null、对象、数组；枚举下拉、描述、可选字段省略、动态字段；整对象 JSON 编辑需要显式点击。非法草稿不可通过切换模式绕过表单验证。
- [x] AI API Key 密码输入与眼睛图标，通过 `/api/credentials/protect` 调用原有加密管理器；响应禁止缓存，资源中仅保存密文。加密失败不保存；后续资源保存失败保留密文重试，不再次请求用户输入密钥。
- [x] include_counts=True 同步两端；回归断言同步检查计数正文经过分析、持久化与中断恢复仍一致，显式 False 保留。

已通过：前端单元测试累计 31 项（基础与编辑器 26 项、参数表单 5 项）；凭据 HTTP 与交互测试 28 项；工作流默认/真实集成/覆写 16 项；迁移后的恢复、跨进程恢复及生命周期 39 项。其他已执行的配置、资源存储、管理器、调度与生命周期回归亦通过。所有后端运行均有 `timeout 60` 硬限制。

验证环境说明：首次测试时，`tests/test_workflow_lifecycle.py` 仍采用旧的同级导入，相关批次显式设置 `PYTHONPATH=tests` 运行；并行的测试整理工作随后迁移到 `tests/workflow/`，已确认本次计数断言被保留，并在新路径下无额外 PYTHONPATH 重跑 39 项全部通过。Chromium 初次启动因缺少 libnspr4/libnss3/libasound 失败，已将发行版包解压到 `/tmp/logagent-browser-libs/root`，浏览器验证显式传入 LD_LIBRARY_PATH；不改应用代码来绕过启动失败。

浏览器验证补充根因：原 AI 表单将 base_url 标为可选，但 `ai/options.py::validate_config` 要求 http provider 提供有效服务地址。已同步为 HTTP 地址必填，避免在输入凭据后才收到笼统业务校验失败。

最终验证：

- [x] 前端 `vue-tsc` 类型检查、受影响文件 Prettier 检查、生产构建通过。
- [x] 受影响 Python 文件 Ruff 检查通过；diff 空白检查通过（原有 CRLF 文件按 cr-at-eol 检查）。
- [x] Playwright 四个真实 API 场景均验证通过：资源字段式排序参数/非法 JSON/创建编辑；工作流来源排序/保存重载/执行/阶段读取；移动端页面无溢出；AI Key 掩码切换/自动 UUID/加密保存。失败项修正后分别针对复跑，未跳过断言或伪造成功。
- [x] diff 复核：未增加失败时自动换配置、无效 JSON 静默保存、凭据明文持久化或另造排序执行逻辑。其他并行任务的测试整理及文档修改保留。
- [ ] Cron 调度：按本任务原文明确留待后续修改。
