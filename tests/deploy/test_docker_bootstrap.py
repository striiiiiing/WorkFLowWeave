"""Container initialization preserves state and rejects conflicting plugin ownership."""

import runpy
from pathlib import Path

import pytest

from logagent.models import SystemConfig

initialize = runpy.run_path(
    str(Path(__file__).parents[2] / "deploy/docker/bootstrap.py")
)["initialize"]


def test_restart_preserves_configuration_and_plugin_settings(tmp_path):
    state = tmp_path / "state"
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    location = initialize(state, bundled)
    config = SystemConfig.model_validate_json(location.read_text())
    assert config.host == "0.0.0.0"
    assert config.data_dir == str(state / "data")
    assert config.master_key_file == str(state / "master.key")
    config.max_concurrent_runs = 2
    location.write_text(config.model_dump_json())
    settings = state / "plugins/config.json"
    settings.write_text('{"channel":{"email":{"enabled":false}}}')
    assert initialize(state, bundled) == location
    assert SystemConfig.model_validate_json(location.read_text()).max_concurrent_runs == 2
    assert settings.read_text() == '{"channel":{"email":{"enabled":false}}}'
    assert (state / "plugins/channel").resolve() == bundled


@pytest.mark.parametrize("symlink", [False, True])
def test_conflicting_channel_directory_fails(tmp_path, symlink):
    channels = tmp_path / "plugins/channel"
    channels.parent.mkdir()
    if symlink:
        channels.symlink_to(tmp_path / "other")
    else:
        channels.mkdir()
    with pytest.raises(RuntimeError, match="Bundled channel"):
        initialize(tmp_path, tmp_path / "bundled")


def test_invalid_existing_config_fails_without_overwriting(tmp_path):
    location = tmp_path / "config.json"
    location.write_text('{"port":0}')
    with pytest.raises(ValueError):
        initialize(tmp_path, tmp_path / "bundled")
    assert location.read_text() == '{"port":0}'
