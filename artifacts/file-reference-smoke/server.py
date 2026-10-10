"""Isolated real lifecycle used for file-reference browser verification."""

import uvicorn

from workflowweave.interaction.app import create_app
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import SystemConfig

config = SystemConfig(
    data_dir="/tmp/workflowweave-file-reference-smoke/data",
    plugin_dir="/tmp/workflowweave-file-reference-smoke/plugins",
    master_key_file="/tmp/workflowweave-file-reference-smoke/master.key",
    host="0.0.0.0", port=14327,
)
uvicorn.run(create_app(ApplicationLifecycle(config)), host=config.host, port=config.port)
