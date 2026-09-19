"""离线校验真实模型测试接受的配置文件格式，不构造模型或 HTTP 响应。"""

import pytest

from ai.live_helpers import read_settings


@pytest.mark.parametrize("body", [
    "http://localhost:19026/v1\nqwen3.7-flash\nfixture-key\n",
    'AI_BASE_URL="http://localhost:19026/v1"\nAI_MODEL=qwen3.7-flash\nAI_API_KEY=fixture-key\n',
], ids=["positional", "named"])
def test_live_settings_support_positional_and_named_config(tmp_path, body):
    """验证逐行格式和变量赋值格式解析为相同的显式测试配置。"""
    path = tmp_path / ".env"
    path.write_text(body)
    assert read_settings(path) == {
        "AI_BASE_URL": "http://localhost:19026/v1",
        "AI_MODEL": "qwen3.7-flash", "AI_API_KEY": "fixture-key",
    }


@pytest.mark.parametrize("body", [
    "", "http://localhost/v1\n", "AI_MODEL=qwen3.7-flash", "UNKNOWN=value",
    "AI_MODEL=a\nAI_MODEL=b", "AI_MODEL=\nAI_BASE_URL=http://localhost/v1",
], ids=["empty", "url_only", "model_only", "unknown", "duplicate", "empty_model"])
def test_live_settings_reject_incomplete_or_ambiguous_config(tmp_path, body):
    """验证空配置、缺项、未知变量、重复变量和空值不会被隐式补全。"""
    path = tmp_path / ".env"
    path.write_text(body)
    with pytest.raises(ValueError):
        read_settings(path)
