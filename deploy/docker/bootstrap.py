"""Initialize container state, then hand process ownership to the existing CLI."""

from __future__ import annotations

import os
from pathlib import Path

from workflowweave.models import SystemConfig

STATE = Path("/var/lib/workflowweave")
BUNDLED_CHANNELS = Path("/app/plugins/channel")


def initialize(state: Path = STATE, bundled_channels: Path = BUNDLED_CHANNELS) -> Path:
    state.mkdir(parents=True, exist_ok=True)
    plugins = state / "plugins"
    plugins.mkdir(exist_ok=True)
    channels = plugins / "channel"
    if channels.is_symlink():
        if channels.readlink() != bundled_channels:
            raise RuntimeError(f"Bundled channel link points to another directory: {channels}")
    elif channels.exists():
        raise RuntimeError(f"Bundled channel path already exists: {channels}")
    else:
        channels.symlink_to(bundled_channels, target_is_directory=True)

    location = state / "config.json"
    if location.exists():
        SystemConfig.model_validate_json(location.read_text(encoding="utf-8"))
        return location
    config = SystemConfig(
        host="0.0.0.0",
        data_dir=str(state / "data"),
        plugin_dir=str(plugins),
        master_key_file=str(state / "master.key"),
    )
    with location.open("x", encoding="utf-8") as stream:
        stream.write(config.model_dump_json(indent=2) + "\n")
    return location


if __name__ == "__main__":
    config_path = initialize()
    os.execvp("workflowweave", ["workflowweave", "start", "--config", str(config_path)])
