import json

import pytest
from pydantic import ValidationError

from logagent.agent.config import AgentConfig
from logagent.agent.storage.bindings import BindingStore
from logagent.agent.storage.settings import SettingsStore


def test_binding_store_persists_session_snapshot_and_fails_closed(tmp_path):
    store = BindingStore(tmp_path / "mcp-bindings")
    binding = {"servers": {"one": {"command": "echo"}}, "sources": []}

    store.write("session_1", binding)
    assert store.read("session_1") == binding
    assert store.read("missing") == {
        "error": "原会话 MCP 绑定丢失或损坏；已有分析仍可读取"
    }

    (tmp_path / "mcp-bindings" / "broken.json").write_text("{", encoding="utf-8")
    assert store.read("broken") == {
        "error": "原会话 MCP 绑定丢失或损坏；已有分析仍可读取"
    }


@pytest.mark.parametrize("session_id", ["", "../escape", "nested/id", r"nested\id", "\x00"])
def test_binding_store_rejects_non_component_session_ids(tmp_path, session_id):
    store = BindingStore(tmp_path)
    with pytest.raises(ValueError, match="single path component"):
        store.read(session_id)


def test_settings_store_loads_explicit_default_copy_and_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    default = AgentConfig(timezone="UTC")

    loaded_default = store.load(default)
    assert loaded_default == default
    assert loaded_default is not default

    saved = AgentConfig(timezone="Asia/Shanghai", read_concurrency=7)
    store.save(saved)
    assert json.loads(path.read_text(encoding="utf-8")) == saved.model_dump(mode="json")
    assert store.load(default) == saved


def test_settings_store_does_not_hide_corrupt_configuration(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValidationError):
        SettingsStore(path).load(AgentConfig(timezone="UTC"))
