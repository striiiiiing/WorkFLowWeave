"""Small, credential-free contracts for a remote frontend/backend boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from workflowweave.errors import WorkFLowWeaveError

_TERMINAL_STATUSES = frozenset(("completed", "partial", "failed", "cancelled", "interrupted"))


@dataclass(frozen=True, slots=True)
class RemoteBackendOrigin:
    base_url: str
    host: str

    @classmethod
    def parse(cls, value: str) -> RemoteBackendOrigin:
        if type(value) is not str or not value.strip():
            raise WorkFLowWeaveError("remote_origin_invalid", "远端后端地址无效")
        try:
            parsed = urlsplit(value.strip())
            host = parsed.hostname
            if parsed.scheme not in {"http", "https"} or not host:
                raise ValueError
            if parsed.username is not None or parsed.password is not None:
                raise WorkFLowWeaveError("remote_origin_credentials", "远端地址不能内嵌凭据")
            if parsed.query or parsed.fragment:
                raise ValueError
            # Accessing port validates malformed numeric ports as well.
            _ = parsed.port
        except WorkFLowWeaveError:
            raise
        except (TypeError, ValueError):
            raise WorkFLowWeaveError("remote_origin_invalid", "远端后端地址无效") from None
        path = parsed.path.rstrip("/")
        base_url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        return cls(base_url=base_url, host=host)


def validate_terminal_snapshot(snapshot: Mapping[str, object], *, session_id: str) -> bool:
    if not isinstance(snapshot, Mapping) or type(session_id) is not str or not session_id:
        raise WorkFLowWeaveError("remote_snapshot_invalid", "远端终态快照无效")
    if snapshot.get("session_id") != session_id:
        raise WorkFLowWeaveError("remote_snapshot_invalid", "远端快照会话身份不匹配")
    version = snapshot.get("version")
    if type(version) is not int or version <= 0:
        raise WorkFLowWeaveError("remote_snapshot_invalid", "远端快照版本无效")
    if snapshot.get("status") not in _TERMINAL_STATUSES:
        raise WorkFLowWeaveError("remote_snapshot_invalid", "远端快照尚未进入终态")
    return True
