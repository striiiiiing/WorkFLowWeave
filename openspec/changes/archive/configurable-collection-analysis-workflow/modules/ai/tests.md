# AI 模块测试

依据 [design.md](./design.md)、[task.md](./task.md) 及用户对 mock 的明确说明：**mock 指 `http://localhost:19026/` 提供的模型 ID `mock`**，使用 OpenAI-compatible `/v1` 路径。测试代码集中在 `tests/ai/`。

## 调用方式与独立性

模型测试直接实例化 AIService，通过 LangChain 和真实 HTTP 连接调用服务。默认请求 `http://localhost:19026/v1` 的 `mock`，密钥从 `.env` 读取；显式设置 `WORKFLOWWEAVE_AI_LIVE=1` 后还可测试 `qwen3.7-flash`。Qwen 使用 `.env` 的地址，模型 ID 固定为用户要求的 `qwen3.7-flash`。

已删除 AI 测试中的 `httpx.MockTransport`、伪造 HTTP 响应及注入假模型的测试。观察请求时只使用 httpx 的 request event hook 记录真实发送内容，不替换传输、不制造响应。其他模块仍使用的测试替身移至 `tests/workflow_ai_helpers.py`，AI 测试不导入它。

测试不启动 Lifecycle、Workflow、配置仓库、通知渠道或数据库，只依赖 AI 实现、公共数据模型/错误类型、LangChain/HTTP 库和用户提供的模型服务。

## 固定代码与测试逻辑

| 文件 | 测试逻辑 |
| --- | --- |
| `tests/ai/conftest.py` | 提供真实 mock/Qwen 配置、凭据和渠道；默认执行 mock 用例，默认跳过 Qwen 用例。 |
| `tests/ai/test_service.py` | 纯配置校验；真实调用检查 system/user 角色、字面提示词替换、请求参数、凭据、usage 和客户端所有权；缺少凭据解析器时确认不发请求。 |
| `tests/ai/test_channels.py` | 思考参数类型与冲突校验；真实 `/models` 发现不覆盖配置，检查请求认证；渠道并发启动、关闭幂等与关闭后禁止请求。 |
| `tests/ai/test_live.py` | 对 mock/Qwen 使用同一套模型发现、六种思考选择、并发、取消通知、关闭和显式重启用例。 |
| `tests/ai/test_env.py` | 配置文件格式校验：URL/model/可选 key 两行或三行格式及标准变量赋值格式；缺项、重复项和未知项报错。 |
| `tests/ai/live_helpers.py` | 配置解析、凭据提供、固定提示词和结果断言。 |

- mock 服务实测返回正文“测试”，成功断言要求 `status=success` 且正文包含“测试”，不把 HTTP 200 单独作为通过依据。
- Qwen 的固定提示词要求返回 `WORKFLOWWEAVE_OK`，断言成功且正文包含该标记。
- 六种思考配置为 `enable_thinking=false`，以及 `enable_thinking=true` 搭配 low/medium/high/xhigh/max。记录真实请求并逐项比对参数，同时要求服务器返回可用结果。
- 模型发现必须包含请求的模型 ID；并发结果分别检查 task_id。取消测试在请求开始时取消任务，检查 cancelled 和一次取消通知；显式重启后重新请求模型验证成功。
- `.env`、连接、认证或上游调用失败直接报错，不使用本地替身兜底。

每次短提示词预算为 60 秒、retries=0、max_tokens=1024：及时暴露调用问题、保留首次失败，并为思考后的短答保留空间。这些是验收值，生产默认值不变。

## 运行方法

默认运行配置检查及真实 mock 模型测试，Qwen 用例跳过：

```bash
rtk proxy timeout 60s uv run --frozen pytest -q tests/ai --junitxml=data/ai-mock-tests.xml
```

仅运行 Qwen 用例：

```bash
rtk proxy env WORKFLOWWEAVE_AI_LIVE=1 timeout 180s uv run --frozen pytest -q tests/ai -k qwen --junitxml=data/ai-qwen-tests.xml
```

`WORKFLOWWEAVE_AI_ENV` 可指定配置文件，默认 `.env`。支持下列格式；密钥可省略以请求无认证服务。

```text
http://localhost:19026/v1
qwen3.7-flash
<实际密钥>
```

```dotenv
AI_BASE_URL=http://localhost:19026/v1
AI_MODEL=qwen3.7-flash
AI_API_KEY=<实际密钥>
```

静态检查：

```bash
rtk proxy uv run --frozen ruff check src/workflowweave/ai tests/ai
```

## 验证边界

当前 mock 服务返回固定内容，验证的是实际 HTTP 调用链及生命周期，不证明其执行提示词推理或区分思考预算。Qwen 成功也不等同于证明内部思考预算；请求参数精确传递可从真实请求观察断言确认。

已删除人为构造 429/5xx、断连、非法响应和阻塞渠道的用例，不再声明这些场景已被当前套件覆盖。用户服务未提供故障注入契约，不虚构上游能力。取消验证本地任务与通知，不承诺远端推理停止计费。

本轮验收结果见下方记录；旧本地模拟传输测试的 91 项结果不作为当前套件证据。

## 本轮验收

- 默认套件：**43 passed、15 skipped，9.67 秒**。包含 28 项纯配置检查与 15 项真实 mock 渠道用例；报告 `data/ai-mock-tests.xml`。
- Qwen 验收：**15 项渠道用例全部通过**；当次按 `-k qwen` 筛选还匹配了 3 项配置文本用例，总计 **18 passed，16.26 秒**，报告 `data/ai-qwen-tests.xml`。随后为配置文本用例设置了清晰 ID，现在同一筛选命令只选择 15 项 Qwen 用例。
- AI 测试目录中已无 MockTransport、假模型工厂或自定义模拟 transport；Ruff 通过。未运行其他模块测试。
