# Server deployment measurements

Status: final measurements in progress against the user's locally built, published GHCR release. Earlier remote builds are excluded from the final comparison.

## Evidence

- `preflight.json`: observed hardware, native core-dependency startup/RSS snapshots, frontend build observations, connection incident and limitations.
- `source-sha256.txt`: local application/plugin/deployment source fingerprints.
- `deployment-sha256.txt`: Dockerfile, Compose and dependency lock fingerprints.
- `prepare-build.py`: historical, rejected remote-build experiment. Do not use it for the published-release test.
- `published-images-local.json`, `imported-images.json`: local/target image identity and layer provenance. The release has no revision label, so no Git commit is inferred from its build timestamp.
- `published-archives-sha256.txt`: local image/source archive hashes, checked after direct SSH transfer. Large transport archives are excluded from Git.
- `cleanup-obsolete.sh`: removes this experiment's old native environment, obsolete base images/build cache and unused Python 3.11 RC/buildx packages. Existing system services are retained.
- `prepare-native.sh`: fresh native installation of all Python channel dependencies using the exact source/locks and Node/bridge artifacts extracted from the published backend image.
- `benchmark.py`: serial service benchmark with systemd/Docker cgroups, three process starts, 60-second idle sample, 60-second four-client health/real CLI collection load, process RSS, working set, CPU, disk and health artifacts.
- `run-benchmarks.sh`: orchestrates native backend, native full stack, Docker backend, Docker full stack. Uses fresh benchmark state without real credentials or active notification instances. The native bridge artifact is copied from the same locked Docker build so both deployments include identical bridge dependencies.

## Measurement rules

CPU 100% means one logical core, not the whole two-vCPU machine. Cgroup CPU includes child CLI processes. RSS sums processes and can double-count shared pages; cgroup working set excludes inactive file cache. Whole-host available memory includes the existing panel, cloud agents and Docker daemon, and is reported separately.

Startup begins when the process/Compose launch is requested, ending only when the health API returns HTTP 200 and `status=ready`. Repeated starts retain state and installed dependencies, with warm OS caches; no cold-boot claim is made. Docker full-stack timing includes the backend healthcheck gating of the frontend.

Disk reporting distinguishes native runtime/source/state, container state, image logical size, actual Docker/containerd stores and build cache. Image virtual sizes cannot be added to infer unique physical usage. Native frontend build dependencies are development/build overhead rather than steady production-runtime data. No LLM inference, external model latency, live platform notifications, large MCP processes or long-term storage growth is measured.

## Server paths and recovery

Source: `/opt/logagent`; native state: `/opt/logagent-native`; raw logs/results: `/opt/logagent-benchmark`. Direct root SSH was established using the local public key; no private key was copied. The target host requires `KexAlgorithms=curve25519-sha256` for reliable handshake on the observed network path.

The final images are built locally and exported with `docker save`; the target only imports them with `docker load`. Do not build images on the benchmark host. The user selected these immutable GHCR releases:

```bash
ghcr.io/striiiiiing/workflowweave-backend@sha256:657d84a17b7b4a1a053052090401b4d6080aaba1647b7de94d6f1324b9f3cd22
ghcr.io/striiiiiing/workflowweave-frontend@sha256:e5b4eb58bc27fbaae7bda91f1f3fdb8a7ccbe8f62008040a7a4af3c4ef77ebd1
```

After validating imported images and fresh native dependency installation, run modes serially. `run-benchmarks.sh` prepares the static frontend and native plugin link. Native configuration uses absolute state/plugin paths; Nginx serves the published `frontend/dist` on 3000 and proxies 127.0.0.1:4300.

```bash
bash artifacts/deployment-20261007/run-benchmarks.sh
```

Copy the raw JSON/JSONL/build logs to this local directory before summarizing results. Keep test failures explicit. A successful build or listening port is not a passed health/workflow/browser check.
