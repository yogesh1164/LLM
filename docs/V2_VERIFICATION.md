# V2 development checkpoint verification

## Completed frontend and isolated activation: 2026-10-24

Started clean on `feature/v2-production-hardening` at `259624a`. Baseline verified
before changes: Windows **248 passed / 8 skipped / 1 XFAIL** (13.67s), Linux
**256 passed / 1 XFAIL** (10.98s). No existing database migration, dotenv overwrite,
production configuration change, public deployment, push or merge.

| Final check | Actual result |
|---|---|
| Windows full backend | **248 passed, 21 PostgreSQL skips, 1 XFAIL**, 16.73s; zero failures |
| Linux full backend with PostgreSQL | **269 passed, 1 XFAIL**, 20.10s; zero skips/failures |
| PostgreSQL cases | **21 passed**: history, schema, constraints, transactional failure/revision, refused downgrade, repeat upgrade, five enabled API surfaces and concurrency |
| Integrated frontend runtime run | **26 passed, zero failures/skips**: 14 client, 9 mocked browser and 3 real browser-to-enabled-API cases |
| Standard frontend command | 23 client/mocked cases; three guarded runtime cases skip without the explicit disposable fixture |
| Process-level drill | **10 groups passed**: schema; health/auth; four crash windows; heartbeat/expiry/stale result; eight requests across two processes; browser integration; synthetic backup/restore |
| Static/dependencies | Ruff, pip check, ESLint, app/test TypeScript, encoding and production build pass; npm audit **0 vulnerabilities** |
| Infrastructure | Base/enabled/disabled Compose validation and local actionlint pass. CI now runs mocked browser tests; hosted Actions remain unrun |
| Review builds | Separate backend/frontend `v2-completion-review` tags built; production :local tags untouched |
| Image smoke checks | Standalone frontend HTTP 200; same-origin API bundle; runtime package managers absent. Backend SDK 2.31.0, durable default off, offline fixture excluded |
| Secrets / operator syntax | 109 candidate files passed configured-secret scan; candidate export and 16-commit pre-checkpoint history passed redacted Gitleaks. PowerShell 5.1 runbook blocks parse successfully |
| Preservation | Existing DB/app container IDs/start times and named DB mounts unchanged. All newly created test fixtures stopped; no Docker volumes deleted. main remains 6bd5b32 |

Successful ignored runtime evidence:
`backups/agentflow-v2-durable-e2e-20261024054053/report.json`, redacted
`frontend-tests.log`, generated-only provider call records and a synthetic archive.
Nine content/journal table counts/digests plus the Alembic revision survived restore
to a fresh networkless tmpfs server. SHA-256 matched source, Windows copy and
restore copy. No real production backup/restore or live Gemini request occurred.
The fake SDK stayed synchronous and used `gemini-3.5-flash-lite`.

Corrected harness issues before final passes: Docker Desktop internal-only networks
discarded publishing; fixture APIs now use a separate loopback ingress bridge with
stable ports/readiness deadlines, while the DB stays internal. The guarded fixture
blocks external Python connections. Initial UI selectors also matched Next's route
announcer; selectors now target the submission panel. One initial runtime browser
callback outlived test teardown; awaited status/route cleanup fixed it.

Frontend changes: execution-client.ts, useDurableExecution.ts, ExecutionNotice.tsx,
page.tsx, CustomAgentRunner.tsx, WorkflowBuilder.tsx, globals.css, Playwright config,
three test files, test TypeScript config, package/lockfile and Docker ignore rules.
Next dev generated frontend/AGENTS.md, retained with its local guide instructions.
Backend changes: read-only app/verify_durable_schema.py, expanded PostgreSQL tests,
guarded offline runtime module and repeatable runtime verifier. Migration 0006 is
unchanged. Operator assets: inactive enabled/disabled overlays, private HTTPS checker
and [exact PowerShell rollout/rollback](V2_DURABLE_ROLLOUT.md).

Known limitations remain: synchronous cancellation XFAIL; unknown provider outcomes;
new-key/cross-tab duplicates; lost keys after stale restores; unjournaled legacy
records; shared bearer scope/runtime DB privileges. Prior scans remain **9 backend /
8 frontend high, zero critical**. No suppression/security waiver; builds are not clean
scan evidence. Production migration/activation require explicit operator approval.

## Durable execution verification: 2026-10-24

Started clean at `89958d4` on `feature/v2-production-hardening`. These are source
development checks, not evidence of an enabled production release.

| Check | Actual result |
|---|---|
| Final Windows full suite, repository-root CI command | **248 passed, 8 skipped, 1 XFAIL**, 13.14s; skips require the isolated PostgreSQL fixture URL |
| Final Linux full suite including real PostgreSQL, repository-root command | **256 passed, 1 XFAIL**, 12.00s; zero skips, no network outside the fixture namespace |
| New coverage | 29 offline journal/API/migration cases and 8 PostgreSQL cases, plus two existing auth-inventory parameter cases for the new protected journal route |
| Focused PostgreSQL | 8 passed: concurrent admission, competing recovery, row-lock deferral, stale-worker fencing, tombstones, additive migration/legacy preservation, child-process crash and live heartbeat |
| Ruff / Python dependencies | `ruff check backend` and `pip check` pass |
| Frontend | ESLint, TypeScript, encoding and Next production build pass. No frontend source changes. Build-generated next-env.d.ts change restored |
| CI | Added disposable PostgreSQL job; actionlint passes locally. No hosted run or push |
| Secrets | Configured-secret check passed for 93 candidate files; redacted Gitleaks passed on the candidate export and 15-commit pre-checkpoint history |
| Preservation | Existing DB container IDs, start times and named mounts unchanged. Temporary PostgreSQL fixture stopped; no Docker volumes deleted. Local main remains 6bd5b32 |
| Compose | Production configuration validates without changing or starting any service |
| Migration | 0006 tested on new SQLite files and random schemas inside the new temporary PostgreSQL fixture only. No existing development/production migration |
| SDK | Existing strict cancellation XFAIL unchanged. Fake SDK tests prove durable retries disabled and expired worker dispatch rejected; no live Gemini calls |
| Image security | Not rescanned/rebuilt this continuation; prior review findings remain 9 backend / 8 frontend high, zero critical. No suppression or release-gate change |

The initial combined Linux run reported 254 passes / 2 observability failures /
1 XFAIL: in-process Alembic fixture fileConfig disabled application loggers. The
fixture now uses a migration Config without logging side effects; 11 PostgreSQL
and observability cases passed together before the clean full reruns. The Windows
repository-root collection check also caught a pre-existing `tests` import-path
problem; pytest's configured backend pythonpath now makes CI's root command work.
An initial test invocation named a nonexistent test_database.py and ran no tests;
the corrected initial model/config/workflow run passed 8 tests.

The Linux harness uses the existing constrained review-test image with current
app/tests/migrations/config mounted read-only, a read-only root, dropped capabilities
and disposable tmpfs. Its only network is the new PostgreSQL fixture container's
otherwise disconnected namespace. The new fixture has no published ports or Docker
volume mounts. Each PostgreSQL test migrates a fresh schema; the migration-upgrade
test seeds legacy rows only in that schema. It never selects an application DB URL.

Changed files:

- Service/integration: `backend/app/durable_execution.py`, `database.py`, `config.py`,
  `main.py`, `workflow.py`, `custom_agents.py`, `custom_workflows.py`, `research.py`.
- Schema: `backend/migrations/versions/0006_durable_executions.py` (additive only).
- Regression/CI: `backend/tests/test_durable_execution.py`, `test_durable_postgres.py`,
  `backend/pyproject.toml`, `.github/workflows/ci.yml`.
- Defaults/docs: `.env.production.example`, `docs/V2_DURABLE_EXECUTION.md`,
  `V2_ARCHITECTURE.md`, `V2_CHECKPOINT.md`, `V2_SECURITY_AUDIT.md`, this report.

See [protocol and failure limits](V2_DURABLE_EXECUTION.md). Durable mode remains
disabled pending caller/UI integration and a separately approved migration/rollout.
No ownership migrations, pushes, merges, deployments or live database writes.

## Continuation verification: 2026-10-24

Branch and all three required checkpoint commits verified before changes.
Existing uncommitted work was reviewed, completed and tested. No account/ownership
schema changes, production writes, pushes, merges, deployments or paid AI calls.

| Check | Actual result |
|---|---|
| Focused backend regression run | **41 passed**; interruption recovery, workflow and request limits; Ruff passes |
| Full Windows backend suite | **217 passed, 1 XFAIL** in 58.01s; Ruff and pip check pass |
| Full Linux rebuilt-image suite | **217 passed, 1 XFAIL** in 25.75s; no network, read-only root, disposable tmpfs and SQLite, no database mounts |
| Sandbox limitation | Initial focused run: 27 passed, 1 temp-directory permission error. Host rerun: 28 passed before six additional progress regression cases were added |
| Frontend source | ESLint, TypeScript, encoding and production build pass |
| Image builds | Separate backend/frontend `v2-review-hardening` tags built; V1 `:local` tags untouched |
| Image scans | Backend: **9 high / 0 critical**, four Debian source packages. Frontend: **8 high / 0 critical**, three Debian source packages. Release gate remains blocked; no exceptions |
| Runtime helper permissions | Corrected root inspection passes on both rebuilt images: no setuid/setgid regular files; users remain UID 10001/1000 |
| Frontend runtime | Network-isolated non-root container with read-only root: HTTP 200, no browser localhost API, no npm/Corepack/Yarn |
| Static infrastructure | Both Compose configurations validate; both Dockerfiles pass Hadolint at error threshold |
| Git history secrets | Redacted Gitleaks: 14 commits, no leaks before the new checkpoint |
| Candidate configured-secret scan | 88 candidate source files passed; private environment files and operational evidence remain excluded |
| V1 HTTPS read-only check | Explicit local CA validation: root/health/ready 200; dashboard 401 unauthenticated and 200 authenticated |
| Database preservation | Development ID `3eea02ed0717`, production ID `20505198dfda`; start times and volume mounts unchanged during this continuation |
| Remote CI | Still not run; branch remains unpushed |

New ignored evidence: `backups/v2-backend-resume-build.log`,
`v2-frontend-resume-build.log`, `v2-resume-linux-test-build.log`,
`v2-backend-resume-scout.sarif`, `v2-frontend-resume-scout.sarif` and existing
`v2-hardening-image-check.py` / `.mjs` inspection helpers. No operational artifacts
are to be committed. See [vendor/runtime triage](V2_IMAGE_TRIAGE.md) for all nine CVEs.

Rebuilt review image IDs: backend
`sha256:44b73e8c70e254225408b3c501d5d960fe7981edbb3168a5b2cc5619f00673b5`,
frontend `sha256:56f5d714fa61a3dab6ef45bd8e323a5732327d10a99e1866126ae26e6e08dd9d`.

## Historical verification: 2026-10-23

Date: 2026-10-23. Branch: `feature/v2-production-hardening`; base `6bd5b32`.
This is a development checkpoint, not a production release. No V2 deployment,
production writes, migrations, credential changes, pushes or merges were made.

| Check | Verified result |
|---|---|
| Initial baseline | 110 passed, 1 XFAIL; first sandbox run had a Windows temp permission error, host rerun passed |
| Final Windows full backend suite | **183 passed, 1 XFAIL** with constrained dependencies; Ruff and pip check pass |
| Linux V2 backend image tests | **183 passed, 1 XFAIL**, in-memory SQLite, fake provider key, no live AI calls or production volume mounts |
| Linux initial harness correction | Explicit test GEMINI_MODEL overrode a default-settings test; removed test-only override, no model/code expectation changed |
| Cancellation limitation | Existing synchronous worker XFAIL unchanged; bounded worker/queued cancellation tests added |
| Frontend | ESLint, TypeScript, encoding and Next.js standalone production build pass |
| Frontend review runtime | Network-isolated, no host ports: HTTP 200; no browser `localhost:8000`; npm/Corepack/Yarn absent |
| Docker | Both separate `:v2-review` app images built; production tags/containers not replaced; final constraint-pinned backend build is recorded in ignored build log |
| Static infrastructure | Production Compose and optional application limits validate; Hadolint error-threshold checks and actionlint pass before final checkpoint |
| Python dependencies | Initial two unique advisories (certifi, pytest) fixed locally; subsequent pip-audit zero known vulnerabilities. Runtime production certifi already 2026.10.23 |
| npm audit | Zero known vulnerabilities in frontend lockfile |
| Image vulnerability scans | **FAIL / unresolved**: backend 9 high advisories, frontend reduced from 18 to 8 high advisories after removing unused package managers. All remaining reported as not fixed; no critical findings in these scans |
| Secrets | Existing 11-commit Git history and 82-file candidate export passed redacted Gitleaks; configured-secret scan passed; final staged checks required before checkpoint commits |
| Existing production HTTPS | Explicit Caddy CA validation: root/health/ready 200; dashboard unauthenticated 401 and authorized 200; read-only requests |
| Development DB | `llm-postgres-1` ID/start time and `llm_agentflow-postgres` mount unchanged; no writes/restarts/volume operations |
| Production DB | Independently mounted `agentflow-private_postgres-data`, healthy; no migration, restore or data changes |
| Remote CI | Not run: branch has not been pushed; local syntax/tool checks do not prove hosted Actions success |

## Remaining image findings

Shared Debian findings: CVE-2026-53613, CVE-2026-78409, CVE-2026-82560,
CVE-2026-78410, CVE-2026-78408, CVE-2026-53615, CVE-2026-85091,
CVE-2026-76642. Backend additionally reports CVE-2026-84782 (OpenSSL).
Scanner severities are not an exploitability assessment. Review vendor advisories,
runtime reachability and supported patched bases; do not blanket-ignore findings.
The GitHub image job uses Grype, which may report a different set from local Scout.

## Evidence retained locally (ignored)

- `backups/v2-python-audit.json`, `v2-python-audit-fixed.json`
- `backups/v2-npm-audit.json`
- `backups/v2-backend-scout.sarif`, `v2-frontend-scout-final.sarif`
- `backups/v2-backend-build-constraints.log`, `v2-frontend-build-final.log`
- `backups/v2-review-check.py`, `v2-source-scan/`, `v2-frontend-runtime.mjs`

Do not commit these operational artifacts. The review helper's export directory
is intentionally create-once; rerunning requires a fresh name, not deleting it.

## Change inventory

- CI: `.github/workflows/ci.yml`, `.github/dependabot.yml`.
- Backend: `app/config.py`, `main.py`, `research.py`, `workflow.py`,
  `custom_agents.py`, `custom_workflows.py`, new `provider_capacity.py`,
  `observability.py`, inactive `auth_foundation.py`.
- Tests: new `test_provider_capacity.py`, `test_observability.py`,
  `test_auth_foundation.py`, `test_security_boundaries.py`.
- Dependencies/images: `backend/pyproject.toml`, `backend/constraints.txt`,
  both Dockerfiles, `backend/.dockerignore`.
- Frontend: safe image/citation rendering in `ResultsPanel.tsx`, new `error.tsx`.
- Operations: `.env.production.example`, optional `deploy/compose.limits.yml`;
  actual `.env`/`.env.production` unchanged.
- Docs: README, DEPLOYMENT, V2_SECURITY_AUDIT, V2_ARCHITECTURE,
  V2_VERIFICATION and V2_CHECKPOINT.

Verdict: **V2 is not production/multi-user ready.** Safe foundations are tested;
account activation, ownership migration, durable jobs and unresolved image
vulnerabilities remain gates. Existing V1 private services remain running.
