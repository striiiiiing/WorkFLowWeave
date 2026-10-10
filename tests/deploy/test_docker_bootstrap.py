"""Container initialization preserves state and rejects conflicting plugin ownership."""

import runpy
from pathlib import Path

import pytest

from workflowweave.models import SystemConfig

initialize = runpy.run_path(
    str(Path(__file__).parents[2] / "deploy/docker/bootstrap.py")
)["initialize"]


def test_restart_preserves_configuration_and_plugin_settings(tmp_path):
    state = tmp_path / "state"
    location = initialize(state)
    config = SystemConfig.model_validate_json(location.read_text())
    assert config.host == "0.0.0.0"
    assert config.data_dir == str(state / "data")
    assert config.master_key_file == str(state / "master.key")
    config.max_concurrent_runs = 2
    location.write_text(config.model_dump_json())
    settings = state / "user-plugins/config.json"
    settings.write_text('{"channel":{"email":{"enabled":false}}}')
    assert initialize(state) == location
    assert SystemConfig.model_validate_json(location.read_text()).max_concurrent_runs == 2
    assert settings.read_text() == '{"channel":{"email":{"enabled":false}}}'
    assert not (state / "user-plugins/channel").exists()


def test_initialize_preserves_user_plugin_directory(tmp_path):
    plugins = tmp_path / "user-plugins"
    plugins.mkdir()
    user_plugin = plugins / "custom"
    user_plugin.mkdir()
    initialize(tmp_path)
    assert user_plugin.is_dir()


def test_legacy_user_plugins_migrate_without_copying_bundled_channel_link(tmp_path):
    legacy = tmp_path / "plugins"
    legacy.mkdir()
    (legacy / "config.json").write_text('{"channel":{"custom":{"enabled":false}}}')
    custom = legacy / "custom"
    custom.mkdir()
    (custom / "plugin.json").write_text("{}")
    (legacy / "channel").symlink_to(tmp_path / "bundled", target_is_directory=True)
    location = tmp_path / "config.json"
    location.write_text(SystemConfig(
        plugin_dir=str(legacy), data_dir=str(tmp_path / "data"),
    ).model_dump_json())

    initialize(tmp_path)

    config = SystemConfig.model_validate_json(location.read_text())
    assert config.plugin_dir == str(tmp_path / "user-plugins")
    assert (tmp_path / "user-plugins/config.json").read_text() == (
        '{"channel":{"custom":{"enabled":false}}}'
    )
    assert (tmp_path / "user-plugins/custom/plugin.json").read_text() == "{}"
    assert not (tmp_path / "user-plugins/channel").exists()


def test_invalid_existing_config_fails_without_overwriting(tmp_path):
    location = tmp_path / "config.json"
    location.write_text('{"port":0}')
    with pytest.raises(ValueError):
        initialize(tmp_path)
    assert location.read_text() == '{"port":0}'
