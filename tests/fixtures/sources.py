"""Build real CLI calls used by workflow integration tests."""

import json
import sys


def cli_call(text="example"):
    return {
        "kind": "cli",
        "mode": "argv",
        "executable": sys.executable,
        "argv": ["-c", "import sys; sys.stdout.write(sys.argv[1])", text],
    }


def message_call(message):
    return cli_call(json.dumps({"message": message}, separators=(",", ":")))
