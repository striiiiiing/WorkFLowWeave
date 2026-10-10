"""Direct SSH transport for the metered benchmark host (no jump host)."""

import argparse
import shlex
import subprocess
from pathlib import Path

SSH = [
    "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
    "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
    "-o", "KexAlgorithms=curve25519-sha256",
    "-o", "ProxyCommand=python3 /mnt/d/code/LogAgent/artifacts/deployment-20261007/ssh-tcp.py %h %p",
    "root@8.160.169.249",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "put", "get"])
    parser.add_argument("value")
    parser.add_argument("destination", nargs="?")
    args = parser.parse_args()
    if args.action == "run":
        subprocess.run([*SSH, args.value], check=True)
        return
    if not args.destination:
        parser.error("put/get require destination")
    if args.action == "put":
        with Path(args.value).open("rb") as source:
            subprocess.run([*SSH, "cat > " + shlex.quote(args.destination)], stdin=source, check=True)
    else:
        with Path(args.destination).open("wb") as target:
            subprocess.run([*SSH, "cat " + shlex.quote(args.value)], stdout=target, check=True)


if __name__ == "__main__":
    main()
