"""真实 mock/Qwen 测试共用的配置解析、固定输入和结果断言。"""

import shlex
from pathlib import Path


def read_settings(path: Path) -> dict[str, str]:
    """解析测试配置，返回 AI_BASE_URL、AI_MODEL 和可选 AI_API_KEY。

    支持 URL、模型、可选密钥逐行排列，以及标准 NAME=VALUE 格式。命名格式
    允许 export 前缀、引号与注释；缺项、重复名称或未知名称抛出 ValueError，
    文件读取错误直接上抛，不猜测地址、模型或密钥。
    """
    lines = [line.strip() for line in path.read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if lines and lines[0].startswith(("http://", "https://")):
        if len(lines) not in (2, 3):
            raise ValueError("Positional .env requires URL, model, and optional key on separate lines")
        return dict(zip(("AI_BASE_URL", "AI_MODEL", "AI_API_KEY"), lines, strict=False))
    settings = {}
    for line in lines:
        name, separator, value = line.removeprefix("export ").partition("=")
        name = name.strip()
        if not separator or name not in {"AI_BASE_URL", "AI_MODEL", "AI_API_KEY"}:
            raise ValueError("Expected AI_BASE_URL, AI_MODEL, AI_API_KEY assignments")
        if name in settings:
            raise ValueError(f"Duplicate setting: {name}")
        tokens = shlex.split(value, comments=True)
        if len(tokens) != 1:
            raise ValueError(f"Expected one nonempty value for {name}")
        settings[name] = tokens[0]
    if not settings.get("AI_BASE_URL") or not settings.get("AI_MODEL"):
        raise ValueError("AI_BASE_URL and AI_MODEL are required")
    return settings


class Credentials:
    """测试专用凭据解析器，只读取本次测试已解析的配置字典。"""

    def __init__(self, settings):
        """保留测试配置供异步解析使用，不加载生产配置或环境默认凭据。"""
        self.settings = settings

    async def resolve(self, credential):
        """按凭据引用名称取值；配置缺项时让 KeyError 明确暴露。"""
        return self.settings[credential.name]



async def call(service, config, options, *, task_id="live", on_cancel=None):
    """复制测试配置并用固定提示词发起真实模型请求。

    每次为所选模型设置 max_tokens=1024 和指定思考参数；原配置保持不变，
    任务 ID 及取消回调原样交给 AIService。
    """
    current = config.model_copy(deep=True)
    model = next(iter(current.models))
    current.models[model] = {"max_tokens": 1024, **options}
    return await service.execute(
        current, "{input}", "Reply LOGAGENT_OK.", model=model,
        task_id=task_id, on_cancel=on_cancel,
    )


def assert_success(result, config):
    """要求分析成功且正文含模型对应标记：mock 为“测试”，Qwen 为 LOGAGENT_OK。"""
    assert result.status == "success", result.model_dump_json()
    expected = "测试" if next(iter(config.models)) == "mock" else "LOGAGENT_OK"
    assert expected in result.text, result.model_dump_json()
