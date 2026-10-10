"""Reuse the previous measurement implementation, preserving its raw results."""

import importlib.util
from pathlib import Path

previous = Path(__file__).parents[1] / "deployment-20261007/benchmark.py"
spec = importlib.util.spec_from_file_location("measurement", previous)
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)
measurement.OUT = Path("/opt/logagent-benchmark-20261008")

previous_disk = measurement.disk


def disk():
    result = previous_disk()
    path = Path('/usr/local/lib/node_modules')
    if path.exists():
        result[str(path)] = int(measurement.command(['du', '-sx', '-B1', str(path)]).split()[0])
    return result


measurement.disk = disk

if __name__ == "__main__":
    measurement.main()
