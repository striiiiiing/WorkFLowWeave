# Runtime layers and Docker release

## Basis

- User authorized reordering reusable Docker layers and publishing another version on 2026-10-08; the latest correction explicitly retains Nginx and separate frontend/backend containers.
- `design.md` now records the approved runtime target and deployment boundary. `proposal.md` remains unchanged.
- Tool versions remain those already fixed in `Dockerfile`: Python 3.12, uv 0.11.2, Node 24.15.0, Nginx 1.28. Existing lockfiles remain the dependency contract.
- Order stable common tools before project dependencies: Python/Debian, Git/system dependencies, uv/uvx, Node/npm, project dependencies, application code.
- The backend inherits the runtime stage; a separately published runtime image must have the same layer prefix. Compose must only require backend/frontend and expose frontend port 3000.
- Reordering improves reuse but does not promise lower single-install disk usage. Record compressed content, unpacked layers and Docker disk usage separately; do not add runtime to backend twice.
- Freeze the previously published backend source/locks/plugins/bootstrap for this deployment-only release, identified by immutable image digest, rather than publish unrelated changes in the dirty workspace. Reuse the previously published frontend artifact because its deployment behavior is unchanged.
- Release tags use the UTC timestamp to distinguish this publication without inventing a semantic application version. Retain immutable source image digests in the release record.

## Work

- [x] Inspect current deployment, existing published images, credentials and dirty worktree.
- [x] Extract runtime target and reorder uv before Node; preserve Nginx and backend/frontend Compose boundary.
- [x] Update deployment design, documentation and build workflow for shared runtime publication.
- [ ] Build runtime and backend from the frozen published application inputs.
- [ ] Run targeted deployment checks, build checks and a real isolated full-stack smoke test.
- [ ] Verify shared layer prefixes and measure both application images without double-counting runtime.
- [ ] Publish runtime/backend/frontend release tags and update latest after verification.
- [ ] Record registry digests and final evidence; review the scoped diff.
