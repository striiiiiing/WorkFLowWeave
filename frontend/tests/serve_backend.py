"""Playwright 临时真实后端启动器。

在 TemporaryDirectory 内装配真实生命周期、配置及 API，默认绑定回环 14300 端口；
退出时清理临时数据，不访问仓库的实际数据目录。由普通 e2e 配置启动。
"""

import os
from pathlib import Path
from shutil import copytree, ignore_patterns
from tempfile import TemporaryDirectory

import uvicorn

from logagent.interaction.app import create_app
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import SystemConfig

with TemporaryDirectory(prefix="logagent-frontend-test-") as temporary:
    root = Path(temporary)
    copytree(Path(__file__).resolve().parents[2] / "plugins", root / "plugins",
             ignore=ignore_patterns("__pycache__", "*.pyc", "config.json"))
    port = int(os.environ.get("LOGAGENT_E2E_BACKEND_PORT", "14300"))
    config = SystemConfig(
        data_dir=str(root / "data"),
        plugin_dir=str(root / "plugins"),
        master_key_file=str(root / "master.key"),
        host="127.0.0.1",
        port=port,
    )
    uvicorn.run(create_app(ApplicationLifecycle(config)), host=config.host, port=config.port)
