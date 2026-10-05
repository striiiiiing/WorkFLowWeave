"""Install repository plugins into an isolated test configuration directory."""

from pathlib import Path
from shutil import copytree, ignore_patterns


def install_plugins(destination):
    destination = Path(destination)
    source = Path(__file__).resolve().parents[1] / "plugins"
    for package in sorted(source.iterdir()):
        if package.is_dir() and (package / "plugin.json").is_file():
            copytree(package, destination / package.name,
                     ignore=ignore_patterns("__pycache__", "*.pyc"))
    return destination
