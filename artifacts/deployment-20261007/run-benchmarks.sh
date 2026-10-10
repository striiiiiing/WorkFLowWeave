#!/usr/bin/env bash
set -euo pipefail
cd /opt/logagent
out=/opt/logagent-benchmark

test "$(cat "$out/native-channels-install.exit")" = 0
docker image inspect ghcr.io/striiiiiing/workflowweave-backend:latest ghcr.io/striiiiiing/workflowweave-frontend:latest > "$out/imported-images.json"

# The native source archive includes the published image's locked bridge artifact.
test -d plugins/channel/wechat_openclaw/node_modules
frontend=$(docker create ghcr.io/striiiiiing/workflowweave-frontend:latest)
rm -rf frontend/dist
mkdir -p frontend/dist
docker cp "$frontend:/usr/share/nginx/html/." frontend/dist/
docker rm -v "$frontend"
mkdir -p /opt/logagent-native/plugins
if test -L /opt/logagent-native/plugins/channel; then
    test "$(readlink /opt/logagent-native/plugins/channel)" = /opt/logagent/plugins/channel
else
    ln -s /opt/logagent/plugins/channel /opt/logagent-native/plugins/channel
fi
cp artifacts/deployment-20261007/native-nginx.conf /opt/logagent-native/nginx.conf
docker volume create workflowweave_state
python3 -c 'import json; from pathlib import Path; p=Path("/opt/logagent-native/config.json"); c=json.loads(p.read_text()); c["host"]="127.0.0.1"; p.write_text(json.dumps(c,indent=2))'

if test "$#" = 0; then
    set -- native-backend native-full docker-backend docker-full
fi
for mode in "$@"; do
    python3 artifacts/deployment-20261007/benchmark.py "$mode" > "$out/$mode.log" 2>&1
done
date -Ins > "$out/measurements-complete.txt"
