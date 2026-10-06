# P2 资源闭环

根任务：[tasks.md §3](../tasks.md#3-p2--资源闭环)。依赖 P1，可与 P4/P5 并行；交接给 P3。依据：[原设计](../../design-frontend-architecture/design.md) §3.4、§5、§6、§8.2。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/WorkFLowWeave` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权

写 `modules/resources/**`、`pages/resources/**`、`pages/integrations/useSourceUsage.ts`、资源相关 unit 测试；迁移/删除旧 `views/ResourcesView.vue`、`components/resources/*`、`domain/resources.ts` 中资源部分。P1 已移出的 sourceUsage 不再复制回来。P1 确立的 workflows/system 公共查询/投影只消费，不修改其内部实现；路由/bootstrap/依赖/共享 Schema 变更由 GPT-6 Astra medium 集成 worker 按协调者安排串行落盘。

## 公开交接

resources 定义 `SourceUsageView` 和 API 无关编辑输入，pages 将 workflows 来源投影映射后传入。P2 完成同一个 SourceConfigEditor（基础信息/采集参数/处理规则/高级项），冻结只读值与命名动作；保存目标有区分字段的联合类型禁止混用 local/shared/detached 布尔。API 最小 gateway 从页面注入，组件不能自行选择远端保存目标。

资源列表控制器、当前编辑草稿控制器和能力目录各有唯一拥有者。模型列表/凭据保护保留原协议；明文只在当前编辑流程，不能写日志或持久存储。列表刷新不得覆盖打开的草稿；编辑抽屉的 UI 显隐不能产生第二查询。

## 验收与提交

针对性测试涵盖模型/凭据、来源解析、表单/JSON 单值、非法 JSON、失败留草稿、使用位置未知与当前草稿去重、停用绑定和旧模板引用。组件按资源分类、筛选、列表/卡片、供应商、渠道、编辑区拆分，不做视觉重设计。验证顺序为相关单测→type/边界→build→资源页面真实操作及 375px；协调者切换路由后移除对应旧实现并提交。

P3 开工前交接实际组件 props/emits、保存目标联合、gateway 签名及调用样例。首次冻结后如需改签名，先同步 P3，由一方修改资源公开契约。

## 实施证据

下文记录实际公开契约、测试结果和删除范围；最终浏览器与提交证据由集成验收补齐。

### 实施与公开合同（2026-09-25，验收中）

依据原设计 §3.4/§5/§6，`pages/resources/ResourcesPage.vue` 只装配路由分类、弹窗开关与三类查询；`useResourceList` 拥有当前分类目录和删除/启用动作，`useSourceUsage` 页面集成拥有工作流使用位置，`useCapabilities` 由页面创建一次。编辑抽屉不另查目录。SourceList/SourceCard 发出 workflow(id)，页面以 `workflow-edit` 命名路由导航，resources 不导入 Router/system/workflows。

独立 SFC 已落盘：ResourceCategoryNavigation、SourceFilters、SourceList、SourceCard、ProviderList、ChannelList、AIProviderEditor、ChannelEditor、SourceEditorSession/SourceEditorDrawer；唯一 SourceConfigEditor 组合 SourceBasicFields、SourceCollectionFields、SourceProcessingFields、SourceAdvancedFields。AIModelList 与 CredentialEditor 沿用原交互，HTTP/凭据保护/供应商健康检查移入所属控制器。编辑源配置不会使用 local/shared/detached 布尔决定远端保存。

#### P3 冻结输入（实际导出，均从 resources/public 消费）

- `SourceSaveTarget` 保持 P1：`{kind:'shared-resource',resourceId:string} | {kind:'workflow-draft',workflowId:string,sourceId:string}`；未保存资源的初始 resourceId 为空，submit 在用户编号或生成编号确定后传入实际 resourceId，远端 create/replace 由注入 gateway 决定。
- `SourceConfigEditorGateway` 保持 P1：`resolve(sourceId:string, override?:SourceOverride, signal?:AbortSignal):Promise<SourceConfig>`、`save(target:SourceSaveTarget,value:SourceConfig):Promise<void>`。`CredentialProtector` 为 `(plaintext:string)=>Promise<EncryptedCredential>`，API 无关、单独注入，不扩充保存 gateway 的职责。
- `useSourceEditor(input:SourceEditorInput,gateway)` 在当前组件 setup scope 内创建。input 为 `{initial?:SourceConfig,override?:SourceOverride,target:SourceSaveTarget}`；返回 `value:ComputedRef<Readonly<SourceConfig>|undefined>`、`load`（Query）、`save`（AsyncTask）、命名动作 `updateBasic(SourceBasicChanges)`、`updateId(string)`、`selectCollector(string,capability?)`、`updateOptions(JsonObject)`、`updateSetters(JsonObject)`、`updateAdvanced(SourceAdvancedChanges)`、`submit(validate:()=>Promise<boolean>)`。`submit` 返回 P1 显式 action 结果，其 success.value 为已应用的 SourceConfig。
- `SourceConfigEditor` props：`editor:SourceEditorController`、`target:SourceSaveTarget`、`initial:boolean`、`capabilities:readonly SchemaCapability[]`、`protect:CredentialProtector`；emits `saved(value:SourceConfig)`、`cancel()`。editor 只暴露只读领域值和上述动作；四个字段子组件接收只读配置切片，通过命名事件替换，不拥有第二份领域草稿。组件以唯一表单验证阻止非法 JSON 的上次合法值被保存。
- `SourceEditorSession` 是抽屉的 setup/scope 装配入口，props `{initial?,override?,target,gateway,capabilities,usages?:readonly SourceUsageView[],protect}`，emits 同上；内部创建一个 useSourceEditor 并交给 SourceEditorDrawer。P3 可直接复用 Session，也可在自身组件 scope 创建 controller 后使用 SourceConfigEditor。切换编辑身份请卸载前一个 Session 或以身份 key 重建，不能就地更换 initial 后指望覆盖已有草稿。
- `SourceUsageView` 保持 `{id,name,detached}`。`pages/integrations/useSourceUsage({query?,currentDraft?}={})` 接受既有 useWorkflowList 查询，避免 P3 已有列表时再读；currentDraft 是 getter，投影前按同 ID 替换服务端条目后调用 workflows 的唯一 sourceUsage。查询失败返回 undefined，保留旧快照不被误报为零或当前可信数量。

P3 页面装配示例（`applyIndependentSource` 为 P3 自己的唯一草稿命名动作，并非本包新增的工作流函数）：

```ts
const gateway: SourceConfigEditorGateway = {
  resolve: resourceService.resolveSource,
  async save(target, value) {
    if (target.kind === 'workflow-draft') {
      applyIndependentSource(target.sourceId, value)
      return
    }
    await resourceService.replace('sources', target.resourceId, value)
    await sourceCatalog.refresh()
  },
}
// <SourceEditorSession :target="{ kind:'workflow-draft', workflowId, sourceId }"
//   :initial="source" :override="override" :gateway="gateway"
//   :capabilities="collectors" :protect="resourceService.protectCredential"
//   :usages="usage.references(sourceId)" @saved="closeSourceEditor" />
```

#### 决策依据与行为保留

- 领域值使用 shallowRef + 不可变命名替换。首轮回归发现 spread 深度响应式对象会将嵌套 Vue proxy 带入 structuredClone；改为单个浅容器使领域数据保持普通对象，解决根因而不是 catch clone 失败或 JSON fallback。目录与 editor 无 watch 同步，目录刷新不会重建草稿；resolve 的 signal 在接纳草稿前检查，卸载后结果不能写入。
- legacy template、稀疏 override 及显式 null 原样交给服务端 resolve；前端不再实现另一套 merge。`selectCollector` 仅在能力名称真正变化时清 options/setters/template，能力目录后到不会清空保存字段；手写资源编号保留。来源 60 秒、渠道 30 秒、AI 600 秒/5 次重试保持原 domain/resources.ts 与原设计 §12.2 的后端默认依据。
- 凭据明文只留当前编辑控制器。保护成功而资源保存失败时保留密文并清空明文，重试不再重复保护；保护失败保留当前输入并展示错误。条件 Schema 仍由共享 Ajv 验证，清除凭据保留显式 null。
- 资源回归暴露共享 ParameterField 的旧缺陷：excludedProperties 原先只隐藏表单行，JSON 仍展示密文。已交唯一公共集成 worker 修复 JsonField/ParameterField：raw 投影隐藏值、禁止在 raw 里写入隐藏字段、与隐藏值合并后用原 FieldRule/Ajv 验证，不删 required/条件、不引入第二验证器。资源专属测试验证不反显密文、条件验证与保存密文完整性。
- 目录查询失败仅显示错误，不把空数据占位显示成“暂无资源”；使用位置失败变未知，引用筛选不将未知当未使用。停用来源的绑定/配置不被自动删除，保存现有 source.enabled=false 原样保留。

#### 迁移与验收状态

已删除旧 `components/resources/{ResourceEditor,AIProviderEditor,AIModelList,CredentialEditor}.vue`。SourceSummary 旧路径只 re-export 唯一模块实现；旧 SourceEditorDrawer 为当前 SourceStepCard 保留薄装配，将 local 转为联合 target 后复用同一 SourceEditorSession。该薄出口仅服务未迁移工作流，仍暂从旧页面服务读取能力，P3 迁移 SourceStepCard 时必须删除，最迟 P7 清零。`domain/resources.ts`、`domain/forms.ts` 为唯一实现薄出口，P3/P7 删除；没有第二份资源编辑实现。旧 ResourcesView 暂为新 page 薄出口，公共路由切换后由 P2 删除。

- 首轮 5 文件 28 测试：26 通过，2 个 source 保存失败，已按上述浅草稿根因修复；针对失败的 editor/resource-config 12/12 通过。
- 新 source-editor 单独 7/7 通过；新 resource-ownership 首轮 3/3 通过，后补 currentDraft 去重用例单独复验。
- 完整资源针对性 `rtk npm test -- --reporter=dot tests/unit/resources/source-editor.test.ts tests/unit/resources/resource-ownership.test.ts tests/unit/resource-config.test.ts tests/unit/provider-editor.test.ts tests/unit/provider-proxy.test.ts tests/unit/editor.test.ts tests/unit/source-sharing.test.ts`：7 文件/39 项通过，42.18 秒；随后增加 currentDraft 去重，最终计数待下条记录。
- 集成 worker 已报告当前全局 typecheck/architecture 通过（163 源文件、27 fixtures）；最终收尾后将重跑 type/边界→build→真实浏览器。
- 新 `tests/e2e/resources.spec.ts` 准备真实临时后端 375px 流程，覆盖抽屉保存、一次目录查询、刷新保留草稿、停用来源与三类列表；既有资源 JSON/数组/共享独立流程继续复用。尚未执行，不能据此勾退出。
- 提交由唯一集成 worker 精确处理，上述范围不含后端。此处不将 P0 历史缺口或 P3 完整工作流闭环写作已完成。


补充验收证据：currentDraft 去重加入后 `resource-ownership.test.ts` 4/4 通过（9.12 秒）；旧 `provider-view.test.ts` 已迁移到 ResourcesPage 与 resources/workflows/system 三个注入 key，并新增页面 A→B 编辑身份隔离测试。`provider-view.test.ts + resources/source-editor.test.ts` 2 文件/10 项通过（37.16 秒）。ResourcesPage 每次 open 分配递增 sessionId/key；旧工作流薄抽屉也按 kind:id 重建 Session。useSourceEditor 在 setup 捕获当前 initial/override/saveTarget，避免晚到读取或调用方替换 props 后混用保存身份；未用 watch 覆盖未保存草稿。测试实际在新 Page 连续发出编辑 A、B，验证 A signal aborted、A 晚到后仍是 B 草稿、最终 PUT 仅指向 B。

资源作者已完成差异审查及指定路径 `git diff --check`；P2 业务代码进入稳定窗口，集成 worker 串行切资源路由并删除旧 ResourcesView，进行最终 type/format/architecture、build、真实浏览器与精确提交。最终清单还包含已迁移的 `tests/unit/provider-view.test.ts`。P2 作者不自行 commit、不操作后端或共享配置。

集成职责审查整改：对照原设计 §3.1/§3.2，AI/Channel 控制器最初仍带 FormInstance、ElMessage 与子凭据组件 ref，不能以脚本迁出代替职责分离。已将 form/ref、prepare→validate 的 UI 协调、提示与 saved emit、advanced 显隐全部留在各自 SFC；控制器 API 改为实际方法的 Pick，`submit(validate)` 返回统一显式 action 结果，主体草稿以只读 computed 输出并提供命名更新动作。Channel 与 Source 一样使用浅草稿和不可变替换，避免凭据准备/JSON 合并时带入嵌套响应式代理。整改后 `resource-config/provider-editor/provider-proxy/editor` 4 文件/24 项通过（39.64 秒），涵盖保护失败/保存失败留稿、非法模型 JSON、隐藏凭据条件验证与保存。

公共入口体积检查由集成 worker 发现静态 public UI 将 Ajv/Markdown 拉入 bootstrap；已授权其仅在 resources/public 与 ui/entries.ts 增加 defineAsyncComponent 懒入口，四个重编辑器底层仍为原同名 SFC 唯一实现，公开 props/emits 不变。页面级测试必须等待动态模块 settled 后再检查请求生命周期，不能把懒模块尚未挂载误判为查询丢失。P2 作者未并发修改这两个集成文件。

#### 最终阶段验收记录（2026-09-25）

- P2 实现提交为 `73a55c7`，资源路由与旧资源 View/组件清理提交为 `f6422d4`。两个提交均未包含后端或 P4 文件；提交前后的 staged diff check 均通过，post-commit hook 正常执行。
- 资源单测复验为 9 个文件、57 项通过；typecheck、format:check、架构检查（165 文件及 27 fixtures）和 production build 通过。构建产物将编辑器拆成异步 chunk，ResourcesPage chunk 约 14.63 kB，重编辑器按需加载。
- 配置的真实 FastAPI 临时后端与 Playwright 375px 资源烟测通过（1 passed，20.4s）。测试覆盖一次目录查询、刷新保留草稿、保存回读、停用状态、三类列表和窄屏无横向溢出。Tabbit 运行期间浏览器实例关闭，未形成额外页面证据；Playwright 已提供真实浏览器验收证据。
