"""Project a non-secret SDK login process into a cancellable web session."""

from __future__ import annotations

import asyncio
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from workflowweave.channel.login import TERMINAL_STATES
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.schema import validate_instance

_LOGIN_TIMEOUT = 300.0
_QR_TIMEOUT = 30.0
_STOP_TIMEOUT = 5.0
_LOGIN = str(Path(__file__).with_name("login.mjs"))
_OPTIONS = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "command": {"type": "string", "minLength": 1},
        "state_dir": {"type": ["string", "null"], "minLength": 1},
    },
}
_STATES = {"waiting", "scanned", "verify_required", "connected", "failed"}


class WechatLoginSession:
    def __init__(self, options: dict, *, process_factory=None):
        validate_instance(options, _OPTIONS)
        state_dir = str(Path(options.get("state_dir") or "~/.wechatbot").expanduser().resolve())
        self.scope = state_dir
        self._options = {"state_dir": state_dir, "command": options.get("command", "node")}
        self._status = {"state": "waiting", "message": "正在加载微信 SDK", "qr_url": None,
                        "qr_image": None, "account_id": None, "options": self._options}
        self._factory = process_factory or asyncio.create_subprocess_exec
        self._process = None
        self._task = None
        self._stop_task = None

    def snapshot(self) -> dict:
        return deepcopy(self._status)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="wechat-login")

    async def _run(self) -> None:
        try:
            async with asyncio.timeout(_LOGIN_TIMEOUT):
                self._process = await self._factory(
                    self._options["command"], _LOGIN, "--state-dir", self.scope,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                async with asyncio.timeout(_QR_TIMEOUT) as first_qr:
                    async for line in self._process.stdout:
                        self._project(json.loads(line))
                        if self._status["qr_url"] or self._status["state"] in TERMINAL_STATES:
                            first_qr.reschedule(None)
                        if self._status["state"] in TERMINAL_STATES:
                            return
                raise RuntimeError("login_process_exited")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._status.update(state="failed", qr_url=None, qr_image=None,
                                message=f"微信登录失败（{type(exc).__name__}），请检查网络、Node 依赖及目录权限")
        finally:
            await self._reap()

    def _project(self, event: dict) -> None:
        if not isinstance(event, dict) or event.get("state") not in _STATES:
            raise ValueError("invalid login event")
        url = event.get("qr_url")
        if url is not None:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("invalid QR URL")
        image = event.get("qr_image")
        if image is not None and not re.fullmatch(r"data:image/png;base64,[A-Za-z0-9+/=]+", image):
            raise ValueError("invalid QR image")
        if event["state"] == "connected" and not re.fullmatch(r"\S+", event.get("account_id", "")):
            raise ValueError("missing account ID")
        for key in ("state", "qr_url", "qr_image", "account_id"):
            if key in event:
                self._status[key] = event[key]
        # Messages are local UI text, never platform error payloads or credentials.
        self._status["message"] = {
            "waiting": "用微信扫码并确认登录" if url else "正在获取微信二维码",
            "scanned": "已扫码，请在微信中确认",
            "verify_required": "请输入手机微信显示的数字；若不匹配请重新输入",
            "connected": "登录成功，Token 已保存到本地；请保存资源",
            "failed": "微信登录失败，请检查网络、插件依赖及状态目录写权限",
        }[event["state"]]
        if event["state"] in TERMINAL_STATES:
            self._status.update(qr_url=None, qr_image=None)

    async def verify(self, code: str) -> None:
        if self._status["state"] != "verify_required":
            raise WorkFLowWeaveError("session_not_active", "当前未等待数字确认")
        if not re.fullmatch(r"[0-9]{1,16}", code):
            raise WorkFLowWeaveError("invalid_argument", "确认码必须为 1 至 16 位数字")
        if self._process is None or self._process.returncode is not None:
            raise WorkFLowWeaveError("session_not_active", "登录进程已结束")
        self._process.stdin.write((code + "\n").encode())
        await self._process.stdin.drain()
        self._status.update(state="scanned", message="正在验证数字，请稍候")

    async def _reap(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), _STOP_TIMEOUT)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
