"""Install selected repository plugins into temporary test directories."""

from pathlib import Path
from shutil import copytree, ignore_patterns


def install_plugin(source: str | Path, destination: str | Path) -> Path:
    source, destination = Path(source), Path(destination)
    copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=ignore_patterns("__pycache__", "*.pyc", "node_modules"),
    )
    return destination


def install_test_channel_plugin(destination: str | Path) -> Path:
    root = Path(__file__).resolve().parent / "plugins" / "test_channel"
    return install_plugin(root, Path(destination) / "test_channel")


def install_channel_plugin(name: str, destination: str | Path) -> Path:
    root = (
        Path(__file__).resolve().parents[2]
        / "src/workflowweave/plugins/channel"
        / name
    )
    return install_plugin(root, Path(destination) / name)
