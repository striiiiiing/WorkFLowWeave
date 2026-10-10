#!/usr/bin/env bash
set -euo pipefail
out=/opt/logagent-benchmark
mkdir -p /opt/logagent /opt/logagent-native/plugins
tar -xzf "$out/published-source.tar.gz" -C /opt/logagent
cd /opt/logagent
container=$(docker create ghcr.io/striiiiiing/workflowweave-backend:latest)
docker cp "$container:/usr/local/bin/uv" /usr/local/bin/uv
docker cp "$container:/usr/local/bin/uvx" /usr/local/bin/uvx
docker cp "$container:/usr/local/bin/node" /usr/local/bin/node
docker rm -v "$container"
chmod +x /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/node
# Install with a current standalone Python catalog; the release image uses 3.12.15.
python_root=/opt/workflowweave-python
mkdir -p "$python_root"
tar -xzf "$out/native-python.tar.gz" --strip-components=1 -C "$python_root"
python_path="$python_root/bin/python3.12"
"$python_path" --version
/usr/bin/time -v uv sync --frozen --no-dev --extra channels --no-editable --python "$python_path" > "$out/published-native-install.log" 2>&1
date -Ins > "$out/published-native-install-complete.txt"
python3 -c 'import json; from pathlib import Path; p=Path("/opt/logagent-native"); c={"data_dir":str(p/"data"),"plugin_dir":str(p/"plugins"),"host":"127.0.0.1","port":4300,"max_concurrent_runs":4,"log_file":None,"master_key_env":"WORKFLOWWEAVE_MASTER_KEY","master_key_file":str(p/"master.key")}; (p/"config.json").write_text(json.dumps(c,indent=2))'
printf '0\n' > "$out/native-channels-install.exit"
