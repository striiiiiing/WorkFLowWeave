"""Inspect runtime disk components locally; never start product servers here."""

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
configs = json.loads((HERE / 'comparators.json').read_text())
commands = {
    'openclaw': 'du -x -B1 -d1 /app /usr/local /usr/lib /root 2>/dev/null',
    'hermes': 'du -x -B1 -d1 /opt/hermes /usr/local /usr/lib /root 2>/dev/null; du -x -B1 -d1 /opt/hermes/.venv/lib/python3.13/site-packages 2>/dev/null',
    'qwenpaw': r'du -x -B1 -d1 /app /usr/local /usr/lib /root 2>/dev/null; find /app /usr/local /root -maxdepth 6 -type d -name site-packages -exec du -x -B1 -d1 {} \; 2>/dev/null',
}
for product, config in configs.items():
    for kind, args in {
        'disk-components': ['docker', 'run', '--rm', '--user', '0', '--entrypoint', 'sh', config['image'], '-c', commands[product]],
        'history': ['docker', 'history', '--no-trunc', '--format', '{{.Size}} {{.CreatedBy}}', config['image']],
        'local-image': ['docker', 'image', 'inspect', config['image']],
    }.items():
        result = subprocess.run(args, capture_output=True, text=True)
        (HERE / f'{product}-{kind}.txt').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{product} {kind} failed: {result.stderr}')
    print(f'{product}: saved disk, history, image metadata', flush=True)
