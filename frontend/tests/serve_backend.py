"""Isolated real API for browser tests; never touches the repository data directory."""
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from logagent.interaction.app import create_app
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import SystemConfig

with TemporaryDirectory(prefix="logagent-frontend-test-") as temporary:
    root = Path(temporary)
    config = SystemConfig(
        data_dir=str(root / "data"),
        plugin_dir=str(root / "plugins"),
        master_key_file=str(root / "master.key"),
        host="127.0.0.1",
        port=14300,
    )
    uvicorn.run(create_app(ApplicationLifecycle(config)), host=config.host, port=config.port)
