#!/usr/bin/env bash
set -euo pipefail
cd /opt/logagent
out=/opt/logagent-benchmark
for unit in wwbench-frontend wwbench-backend; do
    if systemctl is-active --quiet "$unit"; then systemctl stop "$unit"; fi
done
du -sx -B1 /opt/logagent/.venv /opt/logagent/src /opt/logagent/plugins /opt/logagent/frontend/dist /opt/workflowweave-python /usr/local/bin/node /usr/local/bin/uv /usr/local/bin/uvx /opt/logagent-native /var/lib/docker /var/lib/containerd /root/.cache/uv > "$out/runtime-disk.txt"
dpkg-query -W -f='${Package} ${Installed-Size}\n' docker.io docker-compose-v2 containerd runc nginx-core git > "$out/runtime-packages-kib.txt"
find src plugins/channel -type f ! -path '*/__pycache__/*' ! -path '*/node_modules/*' -exec sha256sum {} + > "$out/published-source-sha256.txt"
sha256sum pyproject.toml uv.lock plugins/channel/wechat_openclaw/package.json plugins/channel/wechat_openclaw/package-lock.json > "$out/published-locks-sha256.txt"
docker system df -v > "$out/final-image-store.txt"

# Tests are complete: leave only the published Docker deployment and evidence.
rm -rf .venv src plugins frontend /opt/logagent-native /opt/workflowweave-python /root/.cache/uv
rm -f /usr/local/bin/node /usr/local/bin/uv /usr/local/bin/uvx
rm -f "$out/published-images.tar.gz" "$out/published-source.tar.gz" "$out/native-python.tar.gz"
cp artifacts/deployment-20261007/release.env .env
docker compose up -d --no-build --pull never
timeout 90 python3 -c 'import importlib.util, time; s=importlib.util.spec_from_file_location("bench","artifacts/deployment-20261007/benchmark.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); exec("while not m.ready(3000): time.sleep(0.25)")'
docker compose ps > "$out/final-services.txt"
docker compose config > "$out/final-compose.yaml"
docker inspect workflowweave-backend-1 workflowweave-frontend-1 > "$out/final-containers.json"
df -B1 / > "$out/final-filesystem.txt"
du -sx -B1 /var/lib/docker /var/lib/containerd > "$out/final-docker-disk.txt"
curl -fsS http://127.0.0.1:3000/api/health > "$out/final-health.json"
date -Ins > "$out/final-deployment-ready.txt"
