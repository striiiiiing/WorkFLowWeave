#!/usr/bin/env bash
set -euo pipefail
out=/opt/logagent-benchmark
date -Ins > "$out/cleanup-start.txt"
df -B1 / > "$out/cleanup-disk-before.txt"
for unit in wwbench-backend wwbench-frontend; do
    if systemctl is-active --quiet "$unit"; then systemctl stop "$unit"; fi
done
test -z "$(docker ps -q)"
docker builder prune -af > "$out/cleanup-cache.txt"
for image in docker.m.daocloud.io/library/nginx:1.28-alpine docker.m.daocloud.io/library/node:24.15.0-bookworm-slim docker.m.daocloud.io/library/python:3.12-slim-bookworm; do
    docker image rm "$image"
done
rm -rf /opt/logagent /opt/logagent-native /opt/node /root/.cache/uv /root/.npm /root/.local/share/uv
rm -f /usr/local/bin/uv /usr/local/bin/uvx
for binary in node npm npx; do
    test "$(readlink "/usr/local/bin/$binary")" = "/opt/node/bin/$binary"
    rm "/usr/local/bin/$binary"
done
# These packages were newly installed by this experiment, per apt history.
apt-get purge -y python3.11 python3.11-venv python3.11-dev python3.11-minimal libpython3.11 libpython3.11-minimal libpython3.11-stdlib libpython3.11-dev docker-buildx > "$out/cleanup-packages.txt"
df -B1 / > "$out/cleanup-disk-after.txt"
date -Ins > "$out/cleanup-complete.txt"
