# Latest server deployment, public access fix and agent comparison

## Basis

- User requested direct SSH rather than a jump host, investigation/fix of the previous deployment's empty public HTTP response, latest-release native/Docker retesting, local evidence and README results, Docker Hub publication, and serial OpenClaw/Hermes/QwenPaw comparisons on the same metered low-memory server.
- Reuse the approved Nginx/backend container separation in `design.md`. Application changes are contingent on evidence locating the fault in Docker/frontend/backend; preserve explicit failures and avoid symptom-only fixes.
- Use latest backend digest `d38ae390a4f751d30c24e9342abc06a96fd7e810064c74629a4cc4bef8a6f8d7` and frontend digest `e5b4eb58bc27fbaae7bda91f1f3fdb8a7ccbe8f62008040a7a4af3c4ef77ebd1`. Native inputs come from the same release.
- Reuse three starts and 60-second idle/load sampling from the prior benchmark for comparability. CPU 100% is one logical core; report infrastructure overhead and working-set/RSS definitions explicitly.
- Docker Hub's existing credential-helper account is `striiiiiing`; reuse authenticated local credentials without exposing them. Exact additional product sources/versions are recorded before measurements.
- Preserve existing host panel/cloud-agent services and user state. Stop benchmarked applications between modes; never start all products together.
- Keep raw data in `artifacts/deployment-20261008` and finalize README from actual observations. Network/browser/install failures must remain visible.

## Work

- [x] Restore prior results, identify release digests and confirm direct SSH to the target.
- [x] Trace public HTTP requests through the host, Docker network and Nginx. Captures locate failure before the host; UFW explicitly allows 3000 but external probes still fail. Exact external rule and public/browser verification remain unresolved; user clarification requested.
- [x] Deploy latest release and rerun native backend/full-stack and Docker backend/full-stack serially. All requests passed; raw records and summary saved locally. Native disk additionally counts npm's 17,715,200 bytes, omitted previously.
- [ ] Run serial pinned OpenClaw, Hermes and QwenPaw deployment comparisons with idle/startup/disk evidence.
- [x] Publish verified backend/frontend/runtime to Docker Hub and check public manifests anonymously; six tags match GHCR digests. Registry verification is not claimed as a full clean-host image download.
- [ ] Copy all evidence locally, update README and review the diff.
- [ ] Leave the intended WorkFLowWeave deployment healthy; remove only this run's disposable installations/state/caches.

## Interrupted comparison and recovery

- Official pinned manifests, compressed/uncompressed layer bytes, runtime disk components and local Docker storage reports have been saved. Hermes/QwenPaw real local Web preflights passed and their disposable local containers/anonymous volumes were removed; these do not substitute for target-server resource measurements.
- OpenClaw's exact OCI archive passed SHA-256 verification and was imported on the target. WorkFLowWeave was stopped before starting it. Initial target available memory was about 245 MiB during startup; readiness had not passed at the last successful inspection. Subsequent SSH banner exchanges repeatedly timed out. No OOM or exit status was retrieved, so the cause remains unproven.
- User was asked to stop `wwcompare-openclaw` through the cloud console if SSH remained unavailable. Direct SSH cleanup/restoration attempts also could not complete while the connection was unavailable. Do not mark the server cleanup/restoration box complete or assert final service health.
- Subsequent comparator attempts support a documented 768 MiB/no-swap and one-core ceiling, leaving room for original host services. That ceiling changes deployment conditions and must be reported independently of unrestricted measurements. No swap was added.
- README now contains the completed four-mode retest and explicitly incomplete runtime comparisons. Local evidence is preserved in `artifacts/deployment-20261008`; continue remaining target measurements and final cleanup after server access recovers.
