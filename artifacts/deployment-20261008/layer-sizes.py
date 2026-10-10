"""Count validated compressed/uncompressed unique layer tar bytes."""

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
results = {}
for name in ['openclaw', 'hermes', 'qwenpaw']:
    manifest = json.loads((HERE / f'{name}-manifest.json').read_text())
    layers = {item['digest']: item for item in manifest['layers']}
    rows = []
    for value, item in layers.items():
        path = Path('/tmp/ww-comparison-images') / name / 'blobs/sha256' / value.split(':')[1]
        size = 0
        with gzip.open(path, 'rb') as stream:
            for block in iter(lambda: stream.read(2**20), b''):
                size += len(block)
        rows.append({'digest': value, 'compressed_bytes': item['size'], 'uncompressed_tar_bytes': size})
    compressed = sum(row['compressed_bytes'] for row in rows)
    uncompressed = sum(row['uncompressed_tar_bytes'] for row in rows)
    results[name] = {'compressed_bytes': compressed, 'uncompressed_tar_bytes': uncompressed, 'compressed_plus_uncompressed_bytes': compressed + uncompressed, 'layers': rows}
    print(name, compressed, uncompressed, flush=True)
(HERE / 'layer-sizes.json').write_text(json.dumps(results, indent=2))
