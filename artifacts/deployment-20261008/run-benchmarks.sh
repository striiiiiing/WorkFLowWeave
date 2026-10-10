#!/usr/bin/env bash
set -euo pipefail
cd /opt/logagent
out=/opt/logagent-benchmark-20261008
docker compose down
docker image inspect ghcr.io/striiiiiing/workflowweave-backend:latest ghcr.io/striiiiiing/workflowweave-frontend:latest > "$out/imported-images.json"
for mode in native-backend native-full docker-backend docker-full; do
    python3 artifacts/deployment-20261008/benchmark.py "$mode" > "$out/$mode.log" 2>&1
done
date -Ins > "$out/measurements-complete.txt"
