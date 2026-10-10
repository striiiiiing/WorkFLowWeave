# Python, Node, Git, uv layering and release

## Basis

- This task supersedes the in-progress `2026-10-08-runtime-layers` task after the user corrected the approved layer order. Earlier trial images were built but not published.
- User explicitly requested Python, Node/npm, Git, then uv/uvx because Python and Node are more commonly installed. `design.md` was updated under that instruction; `proposal.md` is unchanged.
- Retain the separately deployed Nginx frontend as explicitly requested. Compose only requires backend/frontend, with frontend port 3000 and internal backend port 4300.
- Add a separately publishable runtime target with the same filesystem layer prefix as backend. Project dependencies and code follow the common runtime.
- Publish the reusable target as `workflowweave-backend:runtime` and `runtime-20261007T190805Z` within the existing public GHCR package; this reuses verified public access instead of requiring a third package and separate visibility settings.
- Reuse versions already fixed in `Dockerfile` and existing dependency lockfiles. Do not change application behavior or introduce a private Python runtime into the frontend image.
- Release runtime and backend from the frozen application inputs extracted from published backend digest `sha256:657d84a17b7b4a1a053052090401b4d6080aaba1647b7de94d6f1324b9f3cd22`. Retag unchanged published frontend digest `sha256:e5b4eb58bc27fbaae7bda91f1f3fdb8a7ccbe8f62008040a7a4af3c4ef77ebd1` under the same release version.
- The source freeze avoids publishing unrelated work in the dirty workspace. UTC timestamp tag `20261007T190805Z` identifies the release initiated on 2026-10-08 local time; no semantic application version is invented.
- Report compressed content, unpacked filesystem layers and Docker disk usage separately. Shared runtime is already included in backend and must not be counted twice. The change improves reuse without promising a smaller single deployment.

## Work

- [x] Update runtime layer order, deployment design and documentation according to the latest instruction.
- [x] Preserve the Nginx frontend and the existing Compose deployment boundary.
- [x] Add runtime publication and shared cache use to the local CI workflow.
- [x] Verify bootstrap tests (4 passed), Ruff and Compose/workflow structure before the order correction; these files are unchanged by the correction.
- [x] Rebuild runtime/backend with Python, Node/npm, Git, uv/uvx order.
- [x] Verify runtime layer prefix (9 shared layers), tool versions, dependency locks and frozen source identity (219 files, 106 distributions).
- [x] Perform a real isolated full-stack HTTP smoke test and restart/persistence check. Browser verification was attempted but could not complete because Tabbit closed the pages after navigation.
- [x] Publish versioned runtime/backend/frontend and verify public anonymous runtime access.
- [x] Update latest/runtime aliases and verify all 6 registry tags anonymously.
- [x] Record registry digests, combined deployment size and the scoped diff review.

## Verification

- Bootstrap unit tests: 4 passed; Ruff passed; Compose config and publish-workflow YAML were checked.
- `docker buildx build --check --target backend`: no warnings. Both runtime/backend builds completed.
- Runtime versions: Python 3.12.15, Node 24.15.0, npm 11.12.1, Git 2.39.5, uv/uvx 0.11.2.
- Frozen backend inputs: 219 source/configuration files and all 106 installed Python distribution names/versions match the prior published image.
- Runtime/backend filesystem layer prefix matches exactly for all 9 runtime layers.
- Isolated Compose HTTP checks: `/`, `/agents`, `/workflows/new`, `/docs`, `/redoc`, `/api/health`, `/openapi.json` and entry JS/CSS returned HTTP 200. Health status was `ready` before and after restart; config hash was unchanged. No credentials were configured, so master-key generation was not exercised.
- Browser tooling failed on both GitHub and local pages with `Target page, context or browser has been closed`. The Tabbit task was finished; successful browser rendering is not claimed.
- Measured backend: 188195288 compressed bytes, 652709888 unpacked bytes, 840905176 Docker disk bytes. Frontend: 26533219, 68539970, 95073189 bytes respectively. Combined application images: 214728507 compressed bytes, 721249858 unpacked bytes, 935978365 Docker disk bytes.
- Runtime: 148977869 compressed bytes and 437329920 unpacked bytes, already included in backend. Do not add the separate runtime tag again.
- Source-repository changes remain in the existing dirty workspace; this release publishes Docker images directly from the frozen deployed application inputs. It does not publish unrelated working-tree edits to GitHub.
- Anonymous manifest checks verified backend latest/version/runtime/runtime-version and frontend latest/version. Published backend layers have the exact same 9-layer prefix as the published runtime manifest.
- Isolated smoke containers, their network and the newly created smoke volume were removed. The temporary standalone runtime repository tag was removed after publishing under the existing backend package. Superseded trial tags were replaced before publication; unrelated image/cache entries were not pruned.
- Existing production containers were not restarted or upgraded; they remain running and healthy. Deployment-only updates are available through the new latest image tag.
- Final scoped review found no changes to application behavior, channel dependency versions, Nginx routing or Compose exposure; `git diff --check` passed.

## Published Version Digests

- Backend `20261007T190805Z`: `sha256:d38ae390a4f751d30c24e9342abc06a96fd7e810064c74629a4cc4bef8a6f8d7`.
- Backend `runtime-20261007T190805Z`: `sha256:0f12dff0a2e7ceaa93077c8c2b232128cd043f5dd37f5eb396a7acd717e91923`.
- Frontend `20261007T190805Z`: `sha256:e5b4eb58bc27fbaae7bda91f1f3fdb8a7ccbe8f62008040a7a4af3c4ef77ebd1`, unchanged application artifact.
