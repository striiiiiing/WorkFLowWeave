"""Serve prepares durable user state without changing explicit start semantics."""

import pytest
from typer.testing import CliRunner

from workflowweave.interaction import cli
from workflowweave.models import SystemConfig


@pytest.fixture
def launched(monkeypatch):
    values = []

    async def capture(config):
        values.append(config)

    monkeypatch.setattr(cli, "_serve", capture)
    for key in ("WORKFLOWWEAVE_HOST", "WORKFLOWWEAVE_PORT", "WORKFLOWWEAVE_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    return values


def test_serve_creates_user_state_and_preserves_config(tmp_path, monkeypatch, launched):
    monkeypatch.setattr(cli, "user_data_path", lambda *args, **kwargs: tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0, result.output
    config = launched.pop()
    assert config.host == "127.0.0.1"
    assert config.data_dir == str(tmp_path)
    assert config.plugin_dir == str(tmp_path / "plugins")
    assert config.master_key_file == str(tmp_path / "master.key")
    path = tmp_path / "config.json"
    config.max_concurrent_runs = 7
    path.write_text(config.model_dump_json())
    before = path.read_bytes()
    assert runner.invoke(cli.app, ["serve"]).exit_code == 0
    assert launched[-1].max_concurrent_runs == 7
    assert path.read_bytes() == before


def test_flags_override_environment_and_environment_overrides_config(tmp_path, launched):
    args = ["serve", "--host", "127.0.0.2", "--port", "5432", "--data-dir", str(tmp_path)]
    environment = {"WORKFLOWWEAVE_HOST": "0.0.0.0", "WORKFLOWWEAVE_PORT": "4567",
                   "WORKFLOWWEAVE_DATA_DIR": str(tmp_path / "ignored")}
    runner = CliRunner()
    result = runner.invoke(cli.app, args, env=environment)
    assert result.exit_code == 0, result.output
    assert (launched[-1].host, launched[-1].port) == ("127.0.0.2", 5432)
    assert launched[-1].data_dir == str(tmp_path)
    assert not (tmp_path / "ignored").exists()
    environment["WORKFLOWWEAVE_DATA_DIR"] = str(tmp_path)
    assert runner.invoke(cli.app, ["serve"], env=environment).exit_code == 0
    assert (launched[-1].host, launched[-1].port) == ("0.0.0.0", 4567)


@pytest.mark.parametrize("port", ["0", "65536", "abc"])
def test_invalid_port_fails_before_creating_state(tmp_path, launched, port):
    root = tmp_path / "state"
    result = CliRunner().invoke(cli.app, ["serve", "--data-dir", str(root), "--port", port])
    assert result.exit_code == 2
    assert not launched
    assert not root.exists()


def test_invalid_existing_config_is_not_replaced(tmp_path, launched):
    path = tmp_path / "config.json"
    path.write_text('{"port":0}')
    result = CliRunner().invoke(cli.app, ["serve", "--data-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert path.read_text() == '{"port":0}'
    assert not launched


def test_start_still_passes_explicit_config_path(tmp_path, launched):
    path = tmp_path / "custom.json"
    path.write_text(SystemConfig().model_dump_json())
    result = CliRunner().invoke(cli.app, ["start", "--config", str(path)])
    assert result.exit_code == 0, result.output
    assert launched == [path]
