"""Resolve the optional Node runtime at the WeChat process boundary."""

import importlib.util
import logging
import shutil
import sys
from pathlib import Path

from workflowweave.channel.errors import ChannelDeliveryError


def resolve_node(command: str = "node") -> str:
    if command != "node":
        return command
    spec = importlib.util.find_spec("nodejs_wheel")
    if spec is not None and spec.origin is not None:
        root = Path(spec.origin).parent
        executable = root / ("node.exe" if sys.platform == "win32" else "bin/node")
        if not executable.is_file():
            raise ChannelDeliveryError("wechat_node_invalid", f"Node.js 安装不完整：{executable}")
        return str(executable)
    executable = shutil.which("node")
    if executable is not None:
        return executable
    raise ChannelDeliveryError(
        "wechat_node_unavailable",
        "微信渠道需要 Node.js >=22；请安装 nodejs-wheel-binaries 或系统 Node.js，或指定 command。",
    )


def warn_if_node_unavailable() -> None:
    """Diagnose this optional capability without starting a bridge or blocking the app."""
    try:
        resolve_node()
    except ChannelDeliveryError as exc:
        logging.getLogger(__name__).warning("%s: %s", exc.code, exc)
