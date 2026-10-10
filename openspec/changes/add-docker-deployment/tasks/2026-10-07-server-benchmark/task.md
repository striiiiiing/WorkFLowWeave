# Low-spec server deployment benchmark

## Basis

- User requested direct SSH, native and Docker deployment, local CPU/memory/disk and startup evidence, and README reporting on 2026-10-07.
- User clarified: backend-only and full-stack tests; frontend-only is unnecessary. Full Docker stack must use separate images, service-name routing, and publish only port 3000. This authorizes updating the port paragraph in design.md.
- Dependency and runtime versions come from Dockerfile, uv.lock, and both npm lockfiles. Use all channel dependencies in both deployment modes for comparison.
- Existing SystemConfig defaults and single-process CLI remain the runtime contract. Use fresh benchmark state with no model credentials or platform connections.
- Start timing at process/Compose launch, finish only on HTTP 200 with health status ready. Three starts use existing installed dependencies and state; they are process restarts, not cold OS/page-cache boots.
- Idle sampling: 60 seconds. Fixed load: 60 seconds with four clients repeatedly reading health and collecting a real uname CLI source. Four matches SystemConfig.max_concurrent_runs and is a reproducible light workload; it is not LLM or Agent capacity evidence.
- CPU 100% means one logical core. Memory reports process-tree RSS and cgroup working set separately. Disk distinguishes installed runtime, mutable state, image logical size, actual image store and build cache; summing image virtual sizes overcounts shared layers.
- Baseline machine includes existing panel/security services; whole-host usage is not attributed entirely to this project.
- Official PyPI/Docker Hub requests timed out/reset. Remote-only mirror URLs retain locked versions and package hashes; record this build adaptation explicitly. No TLS verification bypass.

## Work

- [x] Identify hardware and establish direct root SSH using the local public key.
- [x] Make full Compose publish only 3000; add backend-only override exposing localhost:4300.
- [x] Import the user's locally built and published production images; exclude prior remote builds.
- [x] Clean obsolete experiment images/cache, source, native state, virtualenv, Python/Node runtimes and unused Python 3.11 RC/buildx packages before final testing.
- [ ] Install fresh native full-channel dependencies from the exact published source/lock snapshot.
- [ ] Measure native backend, native full stack, Docker backend, Docker full stack serially.
- [ ] Validate health, static assets, API/OpenAPI, real CLI collection and browser workflow.
- [ ] Copy raw JSON/JSONL/logs locally, summarize README and review diff.

## Progress and interruption evidence

- User correction on 2026-10-08: use the locally built GHCR release; do not construct benchmark images on the target. Backend digest `657d84a17b7b4a1a053052090401b4d6080aaba1647b7de94d6f1324b9f3cd22`, frontend digest `e5b4eb58bc27fbaae7bda91f1f3fdb8a7ccbe8f62008040a7a4af3c4ef77ebd1`. Native source and locks are extracted from that release, avoiding differences caused by the dirty local worktree. Neither image provides a Git revision label; image digests are the provenance contract.
- Published backend uses `@wechatbot/wechatbot` 2.2.0; the prior large OpenClaw images are obsolete and excluded. Direct transfer archive hashes match; `docker load` took 21.03 seconds, reported separately from application startup.
- User explicitly requested removal of old experimental artifacts and native construction. Cleanup records live under `/opt/logagent-benchmark/cleanup*`; root disk was about 6.6 GiB used before loading the published images.

- Local deployment/bootstrap unit tests: 10 passed in 13.00 seconds, under a 60-second hard timeout. Benchmark scripts pass Ruff and shell syntax validation; Compose config confirms full stack publishes only 3000.
- Native core-dependency preflight: backend ready in 9.375 seconds; full stack ready in 8.393 seconds. These are single warm-start observations and omit all-channel SDKs; not comparable to the planned final Docker image.
- All native Python channel SDKs subsequently installed successfully. Foundation Python, Node and Nginx Docker images were pulled through an explicit proxy. Docker build uses hash-preserving mirror wheel URLs because UV_INDEX_URL alone does not change frozen wheel URLs.
- At 2026-10-07 21:32 CST, target responds to ICMP and accepts TCP, but SSH server banner and panel HTTP responses time out; same observation from myserver. No root cause yet established. Backend/frontend builds had been concurrent; inspect kernel/OOM logs and resume builds serially once connection recovers.
- Preflight snapshots and reproducible harness are stored locally under artifacts/deployment-20261007. README labels comparison incomplete rather than treating build progress as successful deployment evidence.
