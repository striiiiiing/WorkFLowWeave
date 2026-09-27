# 任务

依据：[任务要求](../backendFix/任务要求.md)、[设计](design.md)、[行为规范](specs/workflow-prompts/spec.md)、远端 `workflowServer` 的提示词复用实现，以及用户确认系统提示词和第二层含 `{input}` 的用户提示词均可逐项覆盖、覆盖控件位于前端高级模式。三层消息解释依据任务要求按顺序列出的一个 system prompt 与两个 user prompt；第二个 user prompt 是每项差异指令。

- [x] 1.1 后端增加共享提示词、单项覆盖和差异用户消息配置；迁移旧资源，保持原模型请求。
- [x] 1.2 后端组合独立消息、排序 fan-in 输入及模型复用，覆盖保存/执行/恢复测试。
- [x] 2.1 前端更新类型、默认值，在高级模式提供分析项与 fan-in 对系统及第二层输入模板的独立覆盖控件和差异指令，并覆盖保存重开与引用维护。
- [ ] 3.1 定向测试、Ruff/类型检查、构建、OpenSpec 严格校验和真实浏览器验收。

默认值理由：共享系统提示词空字符串沿用 `AIConfig.system_prompt` 的空默认；共享输入模板 `{input}` 沿用当前分析项和 fan-in 模板默认。单项覆盖 `null` 表示跟随共享值，避免复制后失去同步。fan-in 默认先放原始输入，依据远端 `FanInConfig.ordered_inputs` 实现。用户进一步澄清：有分析任务时默认复用首项；无分析任务时没有可复用的首项，前端新建 fan-in 用 `reuse_from: null`。已有保存的 `$first` 继续按原值加载。后端保存 Workflow 要求至少一个分析任务，所以空任务状态仅是编辑中的草稿。

后端决策记录：依 [设计](design.md) 的旧请求顺序，迁移器把不含 `{input}` 的旧模板写为 `旧模板 + "\n\n{input}"`，并把旧 AIConfig 系统提示词复制为单项显式覆盖；旧 fan-in 关闭复用，保留原顺序和无 AI 拼接。旧 session 的存档快照只在恢复读取时复用同一转换，不改写存档或放宽新 API。依 [行为规范](specs/workflow-prompts/spec.md)，`reuse_from` 与显式 `ai/model` 互斥，避免配置了复用却实际选中另一模型。本独立分支从 c5545c8 的资源格式 1 迁为 2；与统一调度分支合并时，须先运行调度迁移，再把本提示词迁移接为下一版本，并在一次原子发布中完成。

合并决策记录：依据上述分支合并约束和 [统一调度设计](../unify-workflow-scheduling/design.md)，资源迁移链为 `1 -> 2` 调度、`2 -> 3` 提示词；ResourceStore 先完成两步转换和整体验证，再原子发布一次。已有调度分支的 version 2 文件继续升级提示词；旧 session 快照按同一顺序处理旧字段，存档本身不改写。

前端决策记录：依 [设计](design.md) 的继承语义，覆盖控件只以 `null` 表示跟随共享值，切到单独设置时复制当前共享文本，因此共享空字符串也可成为显式空覆盖。依后端 `FanInConfig.paired_model` 校验，切换复用来源时清除显式 `ai/model`；删除被复用的分析项后若仍有首项则回退 `$first`，否则清空 `reuse_from`，并在 fan-in 临时关闭的草稿中同步更新引用。依 `FanInConfig.ordered_inputs` 默认顺序，编辑器在 `order=[]` 时显示 `$input` 与分析项声明顺序，移动后才保存显式顺序。
