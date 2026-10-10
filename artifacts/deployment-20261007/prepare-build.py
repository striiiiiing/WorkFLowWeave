"""Prepare an explicit, hash-preserving mirror build on the benchmark host."""

from pathlib import Path

root = Path("/opt/logagent")
dockerfile = (root / "Dockerfile").read_text()
dockerfile = dockerfile.replace("# syntax=docker/dockerfile:1\n", "")
for name in ("node:24.15.0-bookworm-slim", "python:3.12-slim-bookworm", "nginx:1.28-alpine"):
    dockerfile = dockerfile.replace(
        f"FROM {name} AS ", f"FROM docker.m.daocloud.io/library/{name} AS "
    )
dockerfile = dockerfile.replace(
    "FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS backend\n",
    "FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS backend\n"
    "ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple UV_HTTP_TIMEOUT=30\n",
)
dockerfile = dockerfile.replace("https://deb.debian.org", "https://mirrors.aliyun.com")
dockerfile = dockerfile.replace(
    "RUN npm ci ", "RUN npm config set registry https://registry.npmmirror.com && npm ci "
)
dockerfile = dockerfile.replace(
    "COPY pyproject.toml uv.lock ./", "COPY pyproject.toml ./\nCOPY uv.benchmark.lock ./uv.lock"
)
(root / "Dockerfile.benchmark").write_text(dockerfile)
lock = (root / "uv.lock").read_text()
(root / "uv.benchmark.lock").write_text(
    lock.replace("https://files.pythonhosted.org/", "https://mirrors.aliyun.com/pypi/")
)
print(
    "Prepared Dockerfile.benchmark and uv.benchmark.lock; dependency versions and SHA256 hashes unchanged."
)
