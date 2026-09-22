"""Single-command bubblewrap execution; disabled means explicit host execution."""

from __future__ import annotations

import os
import shutil
import sys

from logagent.agent.process import run_process
from logagent.errors import LogAgentError


class ShellSandbox:
    def __init__(self, workspace):
        self.workspace = workspace

    def _arguments(self, config):
        binary = shutil.which("bwrap")
        if sys.platform != "linux" or binary is None:
            raise LogAgentError("sandbox_unavailable", "需要 Linux bubblewrap；可在设置中关闭沙箱")
        args = [binary, "--die-with-parent", "--new-session", "--unshare-pid",
                "--unshare-uts", "--unshare-ipc", "--unshare-cgroup-try"]
        if not config.sandbox.network:
            args.append("--unshare-net")
        for directory in ("/usr", "/bin", "/lib", "/lib64", "/sbin"):
            if os.path.exists(directory):
                args += ["--ro-bind", directory, directory]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--dir", "/etc", "--bind", str(self.workspace.root), "/workspace"]
        if config.sandbox.network and os.path.exists("/etc/resolv.conf"):
            args += ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf"]
        for name in ("Catalog", "Artifacts"):
            args += ["--ro-bind", str(self.workspace.runtime / name), "/workspace/" + name]
        # History mixes writable notes with read-only per-session fact directories.
        for directory in sorted((self.workspace.runtime / "History").iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                raise LogAgentError("invalid_runtime", "History 事实目录结构无效")
            args += ["--ro-bind", str(directory), "/workspace/History/" + directory.name]
        return args

    async def run(self, command: str, *, config, cwd: str = ".", timeout: float | None = None):  # noqa: ASYNC109 -- public tool contract
        if not command.strip() or (timeout is not None and timeout <= 0):
            raise LogAgentError("invalid_argument", "命令不能为空，timeout 必须为正数")
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                       "HOME": "/tmp", "TMPDIR": "/tmp"}
        if config.sandbox.enabled:
            logical = await self.workspace.shell_directory(cwd)
            prefix = self._arguments(config) + ["--chdir", logical, "--"]
            probe = await run_process([*prefix, "/bin/true"], env=environment,
                                      deadline_seconds=config.shell_timeout,
                                      output_bytes=config.output_bytes)
            if probe.returncode != 0 or probe.status != "success":
                raise LogAgentError("sandbox_unavailable", "bubblewrap 无法创建实际隔离",
                                    {"diagnostic": probe.stderr.decode("utf-8", errors="replace")})
            argv, working_directory = [*prefix, "/bin/sh", "-c", command], None
        else:
            working_directory = self.workspace.root / cwd
            argv = ["/bin/sh", "-c", command]
        result = await run_process(argv, cwd=working_directory, env=environment,
                                   deadline_seconds=timeout or config.shell_timeout,
                                   output_bytes=config.output_bytes, supervise=True)
        if config.sandbox.enabled and result.stderr.startswith(b"bwrap:"):
            raise LogAgentError("sandbox_unavailable", "bubblewrap 隔离启动失败",
                                {"diagnostic": result.stderr.decode("utf-8", errors="replace")})
        return {"status": result.status if result.status != "success" or result.returncode == 0
                else "failed", "exit_code": result.returncode,
                "stdout": result.stdout.decode("utf-8", errors="replace"),
                "stderr": result.stderr.decode("utf-8", errors="replace"),
                "saved_bytes": len(result.stdout) + len(result.stderr),
                "sandbox": config.sandbox.enabled, "network": config.sandbox.network}
