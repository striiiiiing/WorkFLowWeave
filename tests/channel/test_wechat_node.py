"""WeChat's optional runtime is selected at activation time."""

from types import SimpleNamespace

import pytest

from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.plugins.channel.wechat_openclaw import node


def test_wheel_runtime_is_preferred(tmp_path, monkeypatch):
    root = tmp_path / "nodejs_wheel"
    (root / "bin").mkdir(parents=True)
    executable = root / ("node.exe" if node.sys.platform == "win32" else "bin/node")
    executable.touch()
    monkeypatch.setattr(node.importlib.util, "find_spec", lambda name: SimpleNamespace(
        origin=str(root / "__init__.py"),
    ))
    monkeypatch.setattr(node.shutil, "which", lambda name: pytest.fail("wheel has priority"))
    assert node.resolve_node() == str(executable)


def test_system_runtime_is_used_without_wheel(monkeypatch):
    monkeypatch.setattr(node.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(node.shutil, "which", lambda name: "/opt/node/bin/node")
    assert node.resolve_node() == "/opt/node/bin/node"


def test_missing_runtime_is_explicit(monkeypatch):
    monkeypatch.setattr(node.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(node.shutil, "which", lambda name: None)
    with pytest.raises(ChannelDeliveryError) as error:
        node.resolve_node()
    assert error.value.code == "wechat_node_unavailable"


def test_startup_diagnostic_warns_without_starting_bridge(monkeypatch, caplog):
    monkeypatch.setattr(node.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(node.shutil, "which", lambda name: None)
    node.warn_if_node_unavailable()
    assert "wechat_node_unavailable" in caplog.text


def test_explicit_command_is_preserved(monkeypatch):
    monkeypatch.setattr(node.importlib.util, "find_spec", lambda name: pytest.fail("explicit command"))
    assert node.resolve_node("/custom/node") == "/custom/node"
