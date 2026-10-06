"""One filesystem boundary for Agent tools, runtime mappings and the file API."""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import json
import os
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from logagent.agent.contracts import RuntimeIdentity
from logagent.agent.storage.io import file_io
from logagent.agent.workspace.process import run_process
from logagent.agent.workspace.views import RuntimeSelfView
from logagent.errors import LogAgentError
from logagent.storage_primitives.digest import sha256_bytes

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_CHUNK = 64 * 1024
_RUNTIME_ROOTS = frozenset({"Catalog", "Artifacts", "Sessions"})


def _hash(data: bytes) -> str:
    return sha256_bytes(data)


@contextmanager
def _path_errors():
    try:
        yield
    except OSError as exc:
        code = {
            errno.ENOENT: "file_missing", errno.ELOOP: "path_forbidden",
            errno.ENOTDIR: "path_forbidden", errno.EISDIR: "not_a_file",
            errno.EACCES: "file_permission_denied", errno.EPERM: "file_permission_denied",
        }.get(exc.errno)
        if code is None:
            raise
        raise LogAgentError(code, "文件不存在、类型不符或路径不可访问") from None
    except UnicodeError:
        raise LogAgentError("invalid_text", "文件不是有效的 UTF-8 文本") from None


@contextmanager
def _directory(root: Path, parts: tuple[str, ...], *, create=False):
    fd = os.open(root, _DIRECTORY)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, _DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def _regular(fd: int) -> None:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise LogAgentError("not_a_file", "只支持普通文件和目录")


def _load(parent: int, name: str) -> bytes | None:
    try:
        fd = os.open(name, _READ, dir_fd=parent)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        _regular(stream.fileno())
        return stream.read()


def _atomic_write(parent: int, name: str, content: bytes) -> None:
    temporary = ".agent-" + uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                 0o600, dir_fd=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


class WorkspaceBackend:
    def __init__(self, root: Path, runtime: Path, *, identity: RuntimeIdentity | None = None):
        self.root = root.absolute()
        self.runtime = runtime.absolute()
        self.identity = identity
        self._self_view = RuntimeSelfView(identity)

    async def initialize(self):
        await file_io(self._initialize)

    def _initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime.mkdir(parents=True, exist_ok=True)
        with _directory(self.root, (), create=True) as fd:
            for name in ("Memory", "History", "Catalog", "Artifacts"):
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                with _directory(self.root, (name,)):
                    pass
        for name in ("Catalog", "Artifacts", "History", "Sessions"):
            with _directory(self.runtime, (name,), create=True):
                pass

    def for_identity(self, identity: RuntimeIdentity) -> WorkspaceBackend:
        """Return a view sharing this workspace with a different turn identity."""
        return type(self)(self.root, self.runtime, identity=identity)

    def _location(self, path: str, *, sandbox: bool, write=False):
        if not isinstance(path, str) or "\0" in path:
            raise LogAgentError("invalid_path", "路径必须是无 NUL 的字符串")
        requested = Path(path)
        logical = requested.as_posix()
        runtime_prefix = logical == "Runtime" or logical.startswith("Runtime/")
        if runtime_prefix:
            logical = "" if logical == "Runtime" else logical.removeprefix("Runtime/")
            path = logical or "."
            requested = Path(path)
        if not sandbox:
            candidate = requested if requested.is_absolute() else self.root / requested
            resolved = candidate.resolve()
            if not resolved.is_relative_to(self.root):
                return Path(resolved.anchor), resolved.parts[1:], False
            path = resolved.relative_to(self.root).as_posix()
        elif requested.is_absolute():
            try:
                path = requested.relative_to(self.root).as_posix()
            except ValueError:
                raise LogAgentError("path_forbidden", "路径越出 Agent 工作区") from None
        if PureWindowsPath(path).is_absolute() or "\\" in path:
            raise LogAgentError("path_forbidden", "工作区使用 POSIX 相对路径")
        parts = PurePosixPath(path).parts
        if ".." in parts:
            raise LogAgentError("path_forbidden", "路径不能包含上级目录")
        readonly = runtime_prefix or bool(parts and (
            parts[0] in _RUNTIME_ROOTS
            or (parts[0] == "History" and len(parts) > 1
                and (len(parts) > 2 or not parts[1].endswith(".md")))
        ))
        if readonly and write:
            raise LogAgentError("read_only", "运行事实目录只能读取")
        return self.runtime if readonly else self.root, parts, readonly

    async def read(self, path: str, *, offset: int = 0, limit: int | None = None,
                   sandbox: bool = True, default_limit: int, output_bytes: int):
        if offset < 0 or (limit is not None and limit < 1):
            raise LogAgentError("invalid_argument", "offset 必须非负，limit 必须为正数")
        return await file_io(self._read, path, offset, limit or default_limit,
                             sandbox, output_bytes)

    def _read(self, path, offset, limit, sandbox, output_bytes):
        with _path_errors():
            root, parts, readonly = self._location(path, sandbox=sandbox)
            if self._is_self_path(path):
                return self._read_identity(path, offset, limit, output_bytes)
            if not parts:
                return self._listing(root, parts, path, offset, limit, readonly)
            with _directory(root, parts[:-1]) as parent:
                fd = os.open(parts[-1], _READ, dir_fd=parent)
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                os.close(fd)
                return self._listing(root, parts, path, offset, limit, readonly)
            with os.fdopen(fd, "rb") as stream:
                _regular(stream.fileno())
                digest = hashlib.sha256()
                while chunk := stream.read(_CHUNK):
                    digest.update(chunk)
                stream.seek(0)
                lines, number, used = [], 0, 0
                while True:
                    line = stream.readline(output_bytes + 1)
                    if not line:
                        break
                    if len(line) > output_bytes:
                        raise LogAgentError("output_limit_exceeded", "单行超过文件读取预算")
                    if offset <= number < offset + limit:
                        used += len(line)
                        if used > output_bytes:
                            raise LogAgentError("output_limit_exceeded", "文件分页超过输出预算，请减小 limit")
                        lines.append(line.decode("utf-8"))
                    number += 1
                end = min(offset + len(lines), number)
                return {"status": "success", "kind": "file", "path": path,
                        "content": "".join(lines), "hash": digest.hexdigest(),
                        "offset": offset, "next_offset": end if end < number else None,
                        "total_lines": number, "readonly": readonly}

    def _listing(self, root, parts, path, offset, limit, readonly):
        entries = {}
        with _directory(root, parts) as directory:
            for name in os.listdir(directory):
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                entries[name] = {"name": name,
                                 "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file",
                                 "symlink": stat.S_ISLNK(info.st_mode), "readonly": readonly}
        if root == self.root and parts == ("History",):
            with _directory(self.runtime, ("History",)) as directory:
                for name in os.listdir(directory):
                    entries[name] = {"name": name, "kind": "directory",
                                     "symlink": False, "readonly": True}
        if root == self.root and not parts:
            for name in _RUNTIME_ROOTS:
                entries[name] = {"name": name, "kind": "directory",
                                 "symlink": False, "readonly": True}
            entries["Runtime"] = {"name": "Runtime", "kind": "directory",
                                  "symlink": False, "readonly": True}
        if root == self.runtime and not parts:
            entries["self.json"] = {"name": "self.json", "kind": "file",
                                     "symlink": False, "readonly": True}
        ordered = sorted(entries.values(), key=lambda entry: entry["name"])
        end = len(ordered) if limit is None else min(offset + limit, len(ordered))
        return {"status": "success", "kind": "directory", "path": path,
                "entries": ordered[offset:end], "offset": offset,
                "next_offset": end if end < len(ordered) else None, "readonly": readonly}

    async def write(self, path: str, mode: str, content: str, *, old_text: str | None = None,
                    expected_hash: str | None = None, sandbox: bool = True):
        if mode not in {"overwrite", "append", "replace"}:
            raise LogAgentError("invalid_argument", "未知写入模式")
        if mode == "replace" and not old_text:
            raise LogAgentError("invalid_argument", "精确替换需要非空 old_text")
        return await file_io(self._write, path, mode, content, old_text, expected_hash, sandbox)

    def _write(self, path, mode, content, old_text, expected_hash, sandbox):
        with _path_errors():
            root, parts, _ = self._location(path, sandbox=sandbox, write=True)
            if not parts or parts == ("History",):
                raise LogAgentError("not_a_file", "此路径不是可写文件")
            with _directory(root, parts[:-1], create=True) as parent:
                previous = _load(parent, parts[-1])
                actual_hash = None if previous is None else _hash(previous)
                if expected_hash is not None and (
                    (expected_hash == "*" and previous is not None)
                    or (expected_hash != "*" and expected_hash != actual_hash)
                ):
                    raise LogAgentError("file_conflict", "文件已变更，请重新读取后保存",
                                        {"hash": actual_hash})
                if mode == "replace":
                    if previous is None:
                        raise LogAgentError("file_missing", "精确替换的文件不存在")
                    text = previous.decode("utf-8")
                    if text.count(old_text) != 1:
                        raise LogAgentError("replace_conflict", "old_text 必须恰好匹配一次")
                    data = text.replace(old_text, content, 1).encode("utf-8")
                else:
                    data = (previous or b"") if mode == "append" else b""
                    data += content.encode("utf-8")
                _atomic_write(parent, parts[-1], data)
                return {"status": "success", "path": path, "hash": _hash(data),
                        "bytes": len(data)}

    async def grep(self, pattern: str, *, path: str = ".", glob: str | None = None,
                   limit: int | None = None, sandbox: bool = True,
                   default_limit: int, output_bytes: int):
        maximum = limit if limit is not None else default_limit
        if maximum < 1:
            raise LogAgentError("invalid_argument", "limit 必须为正数")
        binary = shutil.which("rg")
        if binary is None:
            raise LogAgentError("grep_unavailable", "需要安装 ripgrep")
        paths = await file_io(self._search_paths, path, sandbox, glob)
        matches, used = [], 0
        for logical in paths:
            descriptor = await file_io(self._search_file, logical, sandbox, cancel_result=os.close)
            try:
                result = await run_process(
                    [binary, "--json", "--max-count", str(maximum + 1 - len(matches)),
                     "--regexp", pattern, "-"], stdin=descriptor,
                    deadline_seconds=None, output_bytes=output_bytes - used,
                )
            finally:
                os.close(descriptor)
            if result.status != "success":
                return {"status": result.status, "matches": matches,
                        "partial_output": result.stdout.decode("utf-8", errors="replace"),
                        "saved_bytes": used + len(result.stdout), "truncated": True}
            if result.returncode not in (0, 1):
                raise LogAgentError("grep_failed", "ripgrep 执行失败",
                                    {"diagnostic": result.stderr.decode("utf-8", errors="replace")})
            for line in result.stdout.splitlines():
                item = json.loads(line)
                if item["type"] != "match":
                    continue
                data = item["data"]
                excerpt = data["lines"].get("text")
                if excerpt is None:
                    raise LogAgentError("invalid_text", "匹配内容不是有效的 UTF-8 文本")
                matches.append({"path": logical, "line": data["line_number"],
                                "text": excerpt.rstrip("\n")})
                used += len(json.dumps(matches[-1], ensure_ascii=False).encode("utf-8"))
                if len(matches) > maximum:
                    return {"status": "success", "matches": matches[:maximum],
                            "truncated": True, "next": "缩小 path/glob 或提高 limit"}
        return {"status": "success", "matches": matches, "truncated": False}

    def _search_file(self, path, sandbox):
        with _path_errors():
            root, parts, _ = self._location(path, sandbox=sandbox)
            with _directory(root, parts[:-1]) as parent:
                descriptor = os.open(parts[-1], _READ, dir_fd=parent)
            try:
                _regular(descriptor)
                return descriptor
            except BaseException:
                os.close(descriptor)
                raise

    def _search_paths(self, path, sandbox, glob):
        with _path_errors():
            if self._is_self_path(path):
                raise LogAgentError("read_only", "Runtime/self.json 只能通过 read 读取")
            root, parts, readonly = self._location(path, sandbox=sandbox)
            with _directory(root, parts[:-1]) as parent:
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False) if parts else os.fstat(parent)
            if stat.S_ISLNK(info.st_mode):
                raise LogAgentError("path_forbidden", "搜索路径不能为符号链接")
            if not stat.S_ISDIR(info.st_mode):
                return [path] if glob is None or fnmatch.fnmatch(path, glob) else []
            # Enumerate logical mappings; open each file by directory fd at execution time.
            listing = self._listing(root, parts, path, 0, None, readonly)
            results = []
            for entry in listing["entries"]:
                if root == self.runtime and not parts and entry["name"] == "self.json":
                    continue
                if entry["symlink"]:
                    continue
                child = str(PurePosixPath(path) / entry["name"])
                if entry["kind"] == "directory":
                    results.extend(self._search_paths(child, sandbox, glob))
                elif glob is None or fnmatch.fnmatch(child, glob) or fnmatch.fnmatch(entry["name"], glob):
                    results.append(child)
            return results

    async def save_runtime(self, path: str, content: bytes):
        """Service-only writes; never exposed to tools or the file API."""
        parts = PurePosixPath(path).parts
        if not parts or ".." in parts or PurePosixPath(path).is_absolute():
            raise ValueError("Runtime writes require a relative path")
        await file_io(self._save_runtime, parts, content)

    @staticmethod
    def _is_self_path(path: str) -> bool:
        return path in {"Runtime/self.json", "Runtime\\self.json"}

    def _read_identity(self, path, offset, limit, output_bytes):
        return self._self_view.read(
            path, offset=offset, limit=limit, output_bytes=output_bytes,
        )

    async def instructions(self) -> str:
        return await file_io(self._instructions)

    def _instructions(self):
        with _path_errors(), _directory(self.root, ()) as parent:
            content = _load(parent, "AGENTS.md")
            return "" if content is None else content.decode("utf-8")

    async def shell_directory(self, path: str) -> str:
        return await file_io(self._shell_directory, path)

    def _shell_directory(self, path):
        with _path_errors():
            root, parts, _ = self._location(path, sandbox=True)
            with _directory(root, parts):
                return "/workspace/" + "/".join(parts)

    def _save_runtime(self, parts, content):
        with _directory(self.runtime, parts[:-1], create=True) as parent:
            _atomic_write(parent, parts[-1], content)
