"""Save exact manifests and compressed layer totals from pinned references."""

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
products = json.loads((HERE / 'comparators.json').read_text())
summary = {}
for name, product in products.items():
    raw = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', product['image'], '--raw'], check=True, capture_output=True, text=True).stdout
    manifest = json.loads(raw)
    (HERE / f'{name}-manifest.json').write_text(json.dumps(manifest, indent=2))
    layers = {layer['digest']: layer['size'] for layer in manifest['layers']}
    summary[name] = {'reference': product['image'], 'compressed_unique_layers_bytes': sum(layers.values()), 'layer_count': len(manifest['layers'])}
(HERE / 'registry-summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
