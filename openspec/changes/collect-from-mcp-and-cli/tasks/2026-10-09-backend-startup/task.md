# Backend startup repair

## Evidence And Scope

The reported `uv run workflowweave start --config config.json` failure was
reproduced at the `resources` stage. Strict parsing rejected 20 obsolete fields
in the local `data/resources.json`: six fields on each of three sources and
`include_counts` on each of two workflows. All sources already had MCP/CLI
`call` definitions; `collector` and `template` were null, while `options` and
`setters` were empty objects.

Decision basis: the collection contract and
[2026-10-08 cleanup task](../2026-10-08-contract-cleanup/task.md) make MCP/CLI
the sole source contract and remove Collector/Setter and business counts.
Repair the local document directly instead of reintroducing runtime aliases or
weakening strict input validation. No proposal/design change or new default is
needed. The original document is backed up at
`/tmp/logagent-resources-before-startup-fix-20261009.json`.

Startup diagnostics are a separate error-boundary fix: the lifecycle previously
discarded structured validation details and suppressed the exception chain.
Keep its cleanup and error code, retain the domain error's structured details,
and include the diagnostic in the exception message so Uvicorn shows the stage,
exception type, reason code and rejected field paths. Do not include arbitrary
exception text or Pydantic input values.

## Tasks And Validation

- [x] Remove only the 20 obsolete fields in the local resource document; compare
  parsed documents against the backup to verify that all other values match.
- [x] Preserve startup stage and structured domain diagnostics in
  `lifecycle/service.py`.
- [x] Verify invalid resource field diagnostics, omission of secret input/raw
  exception values, and cleanup of acquired resources.
- [x] Run targeted tests first, then lifecycle/logging regression tests with a
  hard 60-second timeout: 3 targeted tests and 26 regression tests passed.
- [x] Ruff, affected-module compileall and `git diff --check` passed.
- [x] Start the real CLI using `config.json`: startup completes and
  `http://127.0.0.1:4300/api/health` returns HTTP 200, `status=ready` and
  `accepting_runs=true`. The smoke-test process completes application shutdown.

## Remaining Limitation

Five historical checkpoint cleanup warnings appeared during the CLI smoke test.
Those stored run snapshots contain the same obsolete fields. They do not block
startup or health readiness. Historical run facts/checkpoints were preserved;
this repair does not rewrite SQLite history or claim that historical run
recovery has been repaired.
