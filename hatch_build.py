"""Build the bundled SPA and WeChat bridge dependencies for release wheels."""

import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebAppBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if version == "editable":
            return
        node = shutil.which("node")
        npm = shutil.which("npm")
        if node is None or npm is None:
            raise RuntimeError("Building release wheels requires Node.js >=22 and npm on PATH.")
        node_version = subprocess.check_output([node, "--version"], text=True).strip()
        if int(node_version.removeprefix("v").split(".")[0]) < 22:
            raise RuntimeError("Building release wheels requires Node.js >=22.")
        root = Path(self.root)
        frontend = root / "frontend"
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)
        subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
        output = frontend / "dist"
        build_data["force_include"][str(output)] = "workflowweave/web_app"

        bridge = root / "src/workflowweave/plugins/channel/wechat_openclaw"
        subprocess.run(
            [npm, "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=bridge, check=True,
        )
        sdk_dependencies = root / "build" / "wechat-node-modules"
        if sdk_dependencies.exists():
            shutil.rmtree(sdk_dependencies)
        shutil.move(bridge / "node_modules", sdk_dependencies)
        build_data["force_include"][str(sdk_dependencies)] = (
            "workflowweave/plugins/channel/wechat_openclaw/node_modules"
        )
