"""Initialize container state, then hand process ownership to the existing CLI."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from workflowweave.models import SystemConfig

STATE = Path("/var/lib/workflowweave")
USER_PLUGINS = "user-plugins"


def _copy_plugin_item(source: Path, destination: Path) -> None:
    if source.is_symlink():
        target = source.readlink()
        if destination.is_symlink() and destination.readlink() == target:
            return
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f"Plugin migration target already exists: {destination}")
        destination.symlink_to(target, target_is_directory=source.is_dir())
        return
    if source.is_dir():
        if destination.exists() and not destination.is_dir():
            raise RuntimeError(f"Plugin migration target is not a directory: {destination}")
        destination.mkdir(exist_ok=True)
        for child in source.iterdir():
            if child.name == "channel" and child.is_symlink():
                continue
            _copy_plugin_item(child, destination / child.name)
        return
    if destination.exists():
        if source.read_bytes() == destination.read_bytes():
            return
        raise RuntimeError(f"Plugin migration target differs: {destination}")
    shutil.copy2(source, destination)


def _migrate_user_plugins(state: Path, config: SystemConfig) -> bool:
    legacy = state / "plugins"
    target = state / USER_PLUGINS
    configured = Path(config.plugin_dir)
    if not configured.is_absolute():
        configured = state / configured
    if configured.resolve() != legacy.resolve():
        target.mkdir(exist_ok=True)
        return False

    target.mkdir(exist_ok=True)
    if legacy.exists():
        for child in legacy.iterdir():
            if child.name == "channel" and child.is_symlink():
                continue
            _copy_plugin_item(child, target / child.name)
    config.plugin_dir = str(target)
    return True


def _write_config(location: Path, config: SystemConfig) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=location.parent, prefix=".config-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(config.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, location)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def initialize(state: Path = STATE) -> Path:
    state.mkdir(parents=True, exist_ok=True)
    plugins = state / USER_PLUGINS
    plugins.mkdir(exist_ok=True)

    location = state / "config.json"
    if location.exists():
        config = SystemConfig.model_validate_json(location.read_text(encoding="utf-8"))
        if _migrate_user_plugins(state, config):
            _write_config(location, config)
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
