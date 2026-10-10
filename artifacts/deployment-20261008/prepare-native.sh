#!/usr/bin/env bash
set -euo pipefail
out=/opt/logagent-benchmark-20261008
mkdir -p /opt/logagent /opt/logagent-native/plugins /opt/workflowweave-python
tar -xzf "$out/published-source.tar.gz" -C /opt/logagent
cd /opt/logagent
container=$(docker create ghcr.io/striiiiiing/workflowweave-backend:latest)
docker cp "$container:/usr/local/bin/uv" /usr/local/bin/uv
docker cp "$container:/usr/local/bin/uvx" /usr/local/bin/uvx
docker cp "$container:/usr/local/bin/node" /usr/local/bin/node
docker cp "$container:/usr/local/lib/node_modules" /usr/local/lib/node_modules
docker rm -v "$container"
ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
tar -xzf "$out/native-python.tar.gz" --strip-components=1 -C /opt/workflowweave-python
/usr/bin/time -v uv sync --no-cache --frozen --no-dev --extra channels --no-editable --python /opt/workflowweave-python/bin/python3.12 > "$out/native-install.log" 2>&1
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/opt/logagent-native')
config = {'data_dir': str(p/'data'), 'plugin_dir': str(p/'plugins'), 'host': '127.0.0.1', 'port': 4300, 'max_concurrent_runs': 4, 'log_file': None, 'master_key_env': 'WORKFLOWWEAVE_MASTER_KEY', 'master_key_file': str(p/'master.key')}
(p/'config.json').write_text(json.dumps(config, indent=2))
PY
ln -s /opt/logagent/plugins/channel /opt/logagent-native/plugins/channel
cp artifacts/deployment-20261007/native-nginx.conf /opt/logagent-native/nginx.conf
frontend=$(docker create ghcr.io/striiiiiing/workflowweave-frontend:latest)
mkdir -p frontend/dist
docker cp "$frontend:/usr/share/nginx/html/." frontend/dist/
docker rm -v "$frontend"
date -Ins > "$out/native-install-complete.txt"
