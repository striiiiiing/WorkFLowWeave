# 配置任务

状态：已完成并提交 `6adffca`；2026-09-17 补齐最终验证记录。

依据：[配置设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型与协议；业务校验通过注入函数连接，不等待下游具体模块。

- [x] 保留已验证的只读注册、插件原子注册、schema/plugin/instance 默认覆盖和 Setter 展开；核对 owner reload 与旧视图不变，补充缺失测试。
- [x] 用 design 指定的 resources.json 原子仓库替换 SQLiteResourceStore：五集合、版本化封套、单进程锁、候选完整校验、临时文件替换后发布；get/list 返回副本，create/replace/upsert 和引用删除冲突明确。删除被替换的 SQLite 实现与出口，不保留两份资源来源。
- [x] 保存时固化 options 默认值但保留 Setter 模板引用及显式覆盖供后续模板更新；snapshot 从同一资源视图展开模板，固定声明的路径。已保存插件缺失不阻断快照；无效新提交拒绝。reload 失败保留有效内存视图。
- [x] 实现 CredentialManager 的 env 引用、认证加密、主密钥读取/首次生成与脱敏；已有密文或无法确认时不得生成替代密钥。使用成熟加密库；默认密钥路径/环境变量沿用 SystemConfig。
- [x] 提供装配所需的校验器/注册视图更新入口，校验不调用付费模型或网络，不反向 save；系统路径以配置文件目录解析。
- [x] 更新受资源存储变化影响的调用者及测试入口；旧数据库不自动解释为 JSON，不伪装成功迁移。
- [x] 定向配置/凭据/引用/并发快照与失败注入测试（60 秒）、lint、构建、真实临时目录保存重开烟测。

## 实际实现与验证（2026-09-16）

- 已完成单一 `data_dir/resources.json` 版本化资源视图：五集合、候选完整校验、单进程锁、临时文件 fsync + 原子替换后发布；get/list/snapshot/resolve 均返回独立副本，保存模式、引用删除冲突、reload 失败保留旧视图均有测试。旧 SQLiteResourceStore 出口和调用点已替换。
- 来源保存时固化 options schema 默认值、插件 defaults 和显式 options；Setter 模板引用保留在资源中，snapshot/resolve 再展开并验证完整 Setter。Mock Collector 的 fields 是任意非空字符串，因此原先 `fields=["invalid"]` 不是非法输入；回归已改为真正违反 schema 的 `fields=[1]`，并增加带语义 validator 的模板更新/未保存 resolve 测试。
- `normalize_options` 使用 `schema.transform_annotations` 统一处理 `$ref`、allOf/anyOf/oneOf、本地条件与嵌套数组/对象中的 `x-logagent-path`、`x-logagent-credential` 注解，避免第二套 schema 解释；channels 即使注入业务 validator 也始终先执行 schema 完整校验。
- CredentialManager 支持 env 引用和 Fernet 密文；主密钥优先环境变量，否则 data_dir 下 0600 文件。首次生成前检查 resources.json，并写入不可覆盖的 `.initialized` 使用证据；密钥丢失、格式错误、环境变量无效或密文不匹配均显式失败，禁止静默轮换。
- 定向验证：`rtk proxy timeout 60s uv run pytest -q tests/test_schema_annotations.py tests/test_config.py tests/test_resource_store.py tests/test_credentials.py` → **92 passed**；全套 `rtk proxy timeout 60s uv run pytest -q` → **388 passed**；`rtk proxy uv run ruff check ...`（Config、schema、相关测试）→ All checks passed；`rtk proxy uv build` 成功生成 sdist/wheel；`rtk proxy git diff --check` 通过。

### 决策依据与默认值

- 五集合与原子候选发布直接依据 config design 的“单一版本化 JSON 封套”和三步提交流程；不保留 SQLite 双来源，避免资源视图分裂。路径只在能力 schema 明确 `x-logagent-path` 时解析，依据 design 对“不能把所有名叫 path 的字段统一重写”的约束。
- Setter 更新重新校验所有引用来源，是 design “受影响 Workflow/Setter 引用校验”和模板未来 snapshot 生效的必要不变量；resolve 复用同一候选校验链路且不发布。
- `.initialized` 是对 design“已有密文或无法确认时不得生成替代密钥”的跨进程证据补强：仅扫描当前 resources.json 无法覆盖尚未保存资源或 SessionStore 中的密文，因此首次使用后永久保留不可覆盖标记，优先安全地拒绝不确定状态。
- 默认值沿用 schema/plugin defaults，并在保存/import 时固化；凭据不在 defaults 中解密，快照只保留 Credential 引用/密文，符合配置与凭据设计。

### 2026-09-17 验证补记

- 本轮基线完整回归：`rtk proxy timeout 60s uv run pytest -q` → **396 passed in 40.04s，退出码 0**（包含 schema 注解测试；此前 388 项为添加这 8 项之前的结果）。
- 实际临时目录烟测：`rtk proxy uv run python -` 验证 JSON 保存/重开一致与 Fernet 加解密往返，退出码 0。测试秘密仅为临时烟测数据，未输出或持久化到项目。
