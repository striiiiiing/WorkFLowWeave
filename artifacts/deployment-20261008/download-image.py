"""Download a public pinned OCI image through the local HTTP proxy."""

import argparse
import concurrent.futures
import hashlib
import json
import tarfile
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(2**20), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('product', choices=['openclaw', 'hermes', 'qwenpaw'])
    parser.add_argument('--dockerhub', action='store_true', help='Use the official identical-digest Docker Hub mirror')
    args = parser.parse_args()
    config = json.loads((HERE / 'comparators.json').read_text())[args.product]
    reference, image_digest = config['image'].split('@')
    if reference.startswith('ghcr.io/') and not args.dockerhub:
        registry, repo = 'https://ghcr.io', reference.removeprefix('ghcr.io/')
        auth_url, service = 'https://ghcr.io/token', 'ghcr.io'
    else:
        registry, repo = 'https://registry-1.docker.io', reference.removeprefix('ghcr.io/')
        auth_url, service = 'https://auth.docker.io/token', 'registry.docker.io'
    auth = requests.get(auth_url, params={'service': service, 'scope': f'repository:{repo}:pull'}, timeout=20)
    auth.raise_for_status()
    headers = {'Authorization': 'Bearer ' + auth.json()['token']}
    manifest = json.loads((HERE / f'{args.product}-manifest.json').read_text())
    root = Path('/tmp/ww-comparison-images') / args.product
    blobs = root / 'blobs/sha256'
    blobs.mkdir(parents=True, exist_ok=True)

    def download(item):
        expected = item['digest'].split(':')[1]
        target = blobs / expected
        if target.exists() and target.stat().st_size == item['size'] and digest(target) == expected:
            print(f'cached {expected[:12]} {item["size"]}', flush=True)
            return
        partial = target.with_suffix('.partial')
        response = requests.get(f'{registry}/v2/{repo}/blobs/{item["digest"]}', headers=headers, stream=True, timeout=(20, 120))
        response.raise_for_status()
        with partial.open('wb') as stream:
            for chunk in response.iter_content(2**20):
                stream.write(chunk)
        if partial.stat().st_size != item['size'] or digest(partial) != expected:
            raise ValueError(f'blob integrity failed: {expected}')
        partial.rename(target)
        print(f'downloaded {expected[:12]} {item["size"]}', flush=True)

    unique = {item['digest']: item for item in [manifest['config'], *manifest['layers']]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(download, unique.values()))
    response = requests.get(f'{registry}/v2/{repo}/manifests/{image_digest}', headers={**headers, 'Accept': manifest['mediaType']}, timeout=20)
    response.raise_for_status()
    raw = response.content
    if hashlib.sha256(raw).hexdigest() != image_digest.split(':')[1]:
        raise ValueError('manifest integrity failed')
    (blobs / image_digest.split(':')[1]).write_bytes(raw)
    (HERE / f'{args.product}-image-config.json').write_bytes((blobs / manifest['config']['digest'].split(':')[1]).read_bytes())
    (root / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
    index = {'schemaVersion': 2, 'manifests': [{'mediaType': manifest['mediaType'], 'digest': image_digest, 'size': len(raw), 'annotations': {'org.opencontainers.image.ref.name': config['image']}}]}
    (root / 'index.json').write_text(json.dumps(index))
    target = root.parent / f'{args.product}.tar'
    with tarfile.open(target, 'w') as archive:
        for child in root.iterdir():
            archive.add(child, arcname=child.name)
    print(f'archive={target} bytes={target.stat().st_size}', flush=True)


if __name__ == '__main__':
    main()
