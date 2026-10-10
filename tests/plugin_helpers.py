"""Install repository plugins into an isolated test configuration directory."""

import os
from pathlib import Path

from tests.fixtures.plugin_helpers import install_plugin


def install_plugins(destination):
    destination = Path(destination)
    source = Path(__file__).resolve().parents[1] / "src/workflowweave/plugins"
    for directory, children, files in os.walk(source):
        children[:] = sorted(name for name in children if name not in {"node_modules", "__pycache__"})
        if "plugin.json" not in files:
            continue
        package = Path(directory)
        relative = package.relative_to(source)
        install_plugin(package, destination / relative)
        children.clear()
    return destination
