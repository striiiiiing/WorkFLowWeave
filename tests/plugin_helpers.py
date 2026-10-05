"""Install repository plugins into an isolated test configuration directory."""

from pathlib import Path
from shutil import copytree, ignore_patterns


def install_plugins(destination):
    destination = Path(destination)
    source = Path(__file__).resolve().parents[1] / "plugins"
    for manifest in sorted(source.rglob("plugin.json")):
        package = manifest.parent
        relative = package.relative_to(source)
        copytree(package, destination / relative,
                 ignore=ignore_patterns("__pycache__", "*.pyc"))
    return destination
