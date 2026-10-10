"""Apply the existing summary algorithm to this run's independent evidence."""

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('summary', HERE.parent / 'deployment-20261007/summarize.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)
summary.ROOT = HERE

if __name__ == '__main__':
    summary.main()
