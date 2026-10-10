"""Measure one real agent service at a time, without model inference."""

import argparse
import importlib.util
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path('/opt/logagent-benchmark-20261008')
STATE = Path('/opt/logagent-comparison')
spec = importlib.util.spec_from_file_location('measurement', HERE.parents[0] / 'deployment-20261007/benchmark.py')
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)
measurement.OUT = OUT


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr}')
    return result.stdout


def ready(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200 and bool(response.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def arguments(product, config, name, memory_mib):
    state = STATE / product
    state.mkdir(parents=True, exist_ok=True)
    args = ['docker', 'run', '-d', '--name', name]
    if memory_mib:
        args += ['--memory', f'{memory_mib}m', '--memory-swap', f'{memory_mib}m', '--cpus', '1']
    if product == 'openclaw':
        state.chmod(0o700)
        os.chown(state, 1000, 1000)
        config_file = state / 'openclaw.json'
        if not config_file.exists():
            gateway = {'mode': 'local', 'port': 18789, 'bind': 'lan', 'controlUi': {'allowedOrigins': ['http://127.0.0.1:18789', 'http://localhost:18789']}}
            config_file.write_text(json.dumps({'gateway': gateway}, indent=2))
            os.chown(config_file, 1000, 1000)
            config_file.chmod(0o600)
        args += ['-p', '127.0.0.1:18789:18789', '-v', f'{state}:/home/node/.openclaw', '-e', f'OPENCLAW_GATEWAY_TOKEN={secrets.token_urlsafe(32)}', config['image'], 'node', 'openclaw.mjs', 'gateway', '--bind', 'lan', '--allow-unconfigured']
    elif product == 'hermes':
        args += ['--network', 'host', '-v', f'{state}:/opt/data', config['image'], 'dashboard', '--host', '127.0.0.1', '--no-open']
    else:
        args += ['--init', '-p', '127.0.0.1:8088:8088']
        for directory in ['working', 'working.secret', 'working.backups']:
            target = state / directory
            target.mkdir(exist_ok=True)
            args += ['-v', f'{target}:/app/{directory}']
        args += [config['image']]
    return args


def group(name):
    pid = run(['docker', 'inspect', '-f', '{{.State.Pid}}', name]).strip()
    path = Path(f'/proc/{pid}/cgroup').read_text().splitlines()[0].split(':', 2)[2]
    return measurement.CGROUP / path.lstrip('/')


def store_disk():
    return {str(path): int(run(['du', '-sx', '-B1', str(path)]).split()[0]) for path in [Path('/var/lib/docker'), Path('/var/lib/containerd')] if path.exists()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('product', choices=['openclaw', 'hermes', 'qwenpaw'])
    parser.add_argument('--memory-mib', type=int, default=0)
    selected = parser.parse_args()
    product = selected.product
    config = json.loads((HERE / 'comparators.json').read_text())[product]
    name = 'wwcompare-' + product
    result = {**config, 'product': product, 'memory_limit_mib': selected.memory_mib, 'cpu_limit_cores': 1 if selected.memory_mib else None, 'date_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'startup_seconds': []}
    image = json.loads(run(['docker', 'image', 'inspect', config['image']]))[0]
    result['image'] = {key: image.get(key) for key in ['Id', 'RepoDigests', 'Size', 'RootFS']}
    result['disk_before_start'] = store_disk()
    try:
        for index in range(3):
            before = time.monotonic()
            run(arguments(product, config, name, selected.memory_mib))
            deadline = before + 180
            while not ready(config['url']):
                status = json.loads(run(['docker', 'inspect', '-f', '{{json .State}}', name]))
                if not status['Running']:
                    raise RuntimeError(f'{product} exited: {status}')
                if time.monotonic() > deadline:
                    raise TimeoutError(f'{product} failed readiness within 180 seconds')
                time.sleep(0.25)
            result['startup_seconds'].append(time.monotonic() - before)
            (OUT / f'{product}-startup.json').write_text(json.dumps(result, indent=2))
            if index < 2:
                run(['docker', 'rm', '-f', name])
                time.sleep(1)
        time.sleep(10)
        result['idle'] = measurement.measure(product, 'idle', [group(name)])
        result['container_state'] = json.loads(run(['docker', 'inspect', '-f', '{{json .State}}', name]))
        result['state_bytes'] = int(run(['du', '-sx', '-B1', str(STATE / product)]).split()[0])
        result['disk_after_start'] = store_disk()
        result['infrastructure_processes'] = run(['ps', '-C', 'dockerd,containerd,containerd-shim-runc-v2', '-o', 'pid,rss,comm'])
        result['status'] = 'measured'
    except Exception as error:
        result['status'] = 'failed'
        result['error'] = repr(error)
        raise
    finally:
        (OUT / f'{product}.json').write_text(json.dumps(result, indent=2))
        logs = subprocess.run(['docker', 'logs', name], capture_output=True, text=True)
        (OUT / f'{product}-container.log').write_text(logs.stdout + logs.stderr)
        existing = run(['docker', 'ps', '-aq', '--filter', f'name=^{name}$']).strip()
        if existing:
            run(['docker', 'rm', '-f', name])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
