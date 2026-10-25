# V2 development checkpoint verification

## Five-blocker continuation — 2026-10-25

| Check | Result / limit |
|---|---|
| Git/CI | Clean baseline `0aab361` on `feature/v2-production-hardening`, matching remote. Two hosted runs at that SHA passed eight jobs and failed backend/frontend Grype HIGH gates. This new local continuation has no hosted run. |
| Windows backend + backup | **377 passed, 42 skipped, 1 XFAIL**, 46 SQLite reflection warnings, 68.19 s. The skipped PostgreSQL/Linux cases were not claimed as locally verified. Focused rclone adapter: **11 passed**. |
| Windows Playwright | Two complete runs: **29 passed, 3 skipped** each, exit code 0 at 42.2 s and 30.4 s. Prior teardown hang did not reproduce. Three guarded runtime cases need the isolated API/PostgreSQL fixture. |
| Static/dependencies | Ruff, pip check, frontend ESLint, TypeScript, nine-file encoding and Next.js 16.4.2 production build passed; npm audit 0 vulnerabilities. Local pip-audit module unavailable. |
| Hosted container/PG/security | At `0aab361`, hosted backend, frontend, least-privilege PostgreSQL, durable PostgreSQL, encrypted-backup drill, dependency-audit, Compose and secrets jobs passed. Both image jobs failed Grype. Exact HIGH inventory is [here](V2_GRYPE_CVE_INVENTORY.md). |
| Local container work | `docker compose` production + accounts + roles + limits `config --quiet --no-interpolate` passed. Docker API unavailable; no isolated PostgreSQL rerun, image build, package-layer inspection, Scout rescan or image smoke check in this continuation. Existing containers/volumes were untouched. |
| Google Drive | No authentication, upload, download or actual off-host restore. Local-only rclone evidence from the prior checkpoint plus new mocked failure test only. |

No production or development database, role, volume, service, environment file,
Drive folder, backup or legacy record was modified. No paid provider call.

## Earlier recovery continuation — 2026-10-25

| Check | Result |
|---|---|
| Recovered worktree | Branch `feature/v2-production-hardening`, base `c08ceeda4ea93a3113e5daa30ca2199481c48cf9`; four modified docs and two untracked backup Python files preserved, no unrelated changes. |
| Real rclone local adapter | Temporary `local-only` config and synthetic age-header fixture; `copyto` succeeded. Initial file-to-file `check` failed, revealing a syntax bug. After correction, filtered directory-to-directory full download check succeeded and the local status JSON recorded `verified`. No Google Drive config/token or network remote was used. |
| Focused final test/lint | `test_rclone_offhost.py`: **10 passed** after the correction; Ruff on the changed Python files passed. Previous complete Windows **376 passed / 43 skipped / 1 XFAIL** and focused backup **24 passed** remain the broader regression results from 2026-10-24; they were not repeated after this narrow command fix. |
| Hosted CI at pushed base SHA | Two completed runs, [40104661375](https://github.com/yogesh1164/LLM/actions/runs/40104661375) and [40104665005](https://github.com/yogesh1164/LLM/actions/runs/40104665005): 8 jobs passed and 2 image jobs failed in each. Passing jobs include backend, frontend with Playwright, PostgreSQL least-privilege and durable tests, synthetic encrypted restore, dependency audit, Compose and secret scan. New local changes are not pushed and have no hosted CI result. |
| Image gates | Backend and frontend builds passed; both Anchore/Grype scans failed the HIGH threshold. Logs list 14 distinct HIGH CVE IDs per image, zero CRITICAL, including zlib CVE-2026-85091. Earlier local Scout reported one HIGH per image. Neither scanner finding set is suppressed or accepted. |
| Debian status | On 2026-10-25 Debian still lists Trixie zlib vulnerable/unfixed; the published amd64 version remains `1:1.3.dfsg+really1.3.1-1+b1`. No supported fix was available for a justified rebuild. |

The successful local-only transfer checks rclone command semantics, not age
authentication or actual off-host delivery. The complete prior age and PostgreSQL
drills remain recorded below. No production or development database/service,
real environment file, Google Drive account or backup was accessed or changed.

## Previous continuation — 2026-10-24, from `c08ceed`

No production or development database, role, volume, service, real environment
file, Google Drive account, or remote backup was accessed or changed. No OAuth
authentication or paid Gemini request was made.

| Check | Result |
|---|---|
| Branch and remote | `feature/v2-production-hardening`; read-only `git ls-remote` returned the same `c08ceeda4ea93a3113e5daa30ca2199481c48cf9` branch SHA. Hosted Actions status was inaccessible and is unverified. |
| New mocked rclone adapter + backup/retention regression | **24 passed**. The mock asserted one canonical `.age` artifact with a matching manifest, `copyto --immutable --no-traverse`, exact target, full readback check, no plaintext acceptance, redacted failure status, and source-change detection. No rclone binary/config or network was used. |
| Full Windows backend + `ops/backup` | **376 passed, 43 skipped, 1 xfailed**, 52.96s, 46 SQLite reflection warnings. PostgreSQL and guarded Linux/image integration cases skipped in this environment. |
| Ruff / pip check | Full `ruff check backend deploy ops` passed; `pip check` reported no broken requirements. |
| Frontend | ESLint, `tsc --noEmit`, encoding check (9 files), and Next production build passed. Playwright reported 29 pass / 3 guarded skips; the runner did not exit after listing all cases and was interrupted during teardown. |
| Dependency audits | `npm audit --audit-level=low`: **0 vulnerabilities**. `pip-audit` unavailable (`No module named pip_audit`); previous final-image audit is recorded in the release evidence. |
| Containers/Linux | Docker, rclone, age and age-keygen executables are not available in this session. Linux backend, PostgreSQL fixture, image build/smoke, Scout, Compose and container secret-scan checks were not rerun. |
| First pytest invocation | The first attempted full run used a basetemp parent that did not exist and produced fixture setup errors before collection could complete. It was corrected and the clean full run above passed. |

The three Playwright skips require the separately configured isolated API and
PostgreSQL fixture. The retained XFAIL remains the synchronous SDK thread
cancellation limitation. No new failure was observed in the corrected Windows
run or mocked backup adapter tests.

## Latest blocker-resolution continuation — 2026-10-24

This section supersedes earlier current-result counts below; older entries remain
historical. Full offline pytest runs from the interrupted continuation:

| Check | Result |
|---|---|
| Linux backend + `ops/backup` | **407 passed, 2 skipped, 1 xfailed**, 148.73s |
| Windows backend + `ops/backup` | **373 passed, 36 skipped, 1 xfailed**, 111.51s |
| Focused Windows ownership mapping, role tests and backup tests | **47 passed, 8 skipped**, 26.32s; 28 SQLite index-reflection warnings |
| Focused ownership PostgreSQL suite | **7 passed, 0 skipped** on a new isolated PostgreSQL fixture (saved agent result) |
| Ruff | `ruff check backend deploy ops`: passed |
| Frontend | ESLint, app/test TypeScript, UTF-8 check, production build passed; npm audit 0 vulnerabilities (saved continuation evidence) |
| Image builds | Backend and frontend review image builds passed |
| Current image scans | Backend 1 HIGH / 0 CRITICAL, 6 MEDIUM, 27 LOW; frontend 1 HIGH / 0 CRITICAL, 1 MEDIUM, 26 LOW. Both fail the HIGH gate. |
| Streaming backup | 300 MiB age round-trip and separate local retrieval hash verified; synthetic PostgreSQL restore matched all 15 tables at revision 0007. `off_host_verified=false`. |

Known skip/xfail counts are retained exactly from pytest output; no failures were
reported in these full runs. The PostgreSQL mapping result is an isolated focused
test run, not evidence of production data migration. Latest immutable image IDs,
scanner evidence and the conservative unresolved CVE disposition are recorded in
[release evidence](V2_RELEASE_EVIDENCE.md) and
[the zlib risk assessment](V2_ZLIB_RISK_ASSESSMENT.md).

Candidate-file checks passed for 30 intended files (configured secrets, private-key
markers and binary/NUL checks); redacted Gitleaks found no candidate findings. A
Gitleaks scan of all 9 `main..HEAD` commits found no leaks. Real environment files,
private key/certificate material, backup archives and operational evidence were
outside the candidate export. The branch is still uncommitted at base
`2c1e7d1ef2f9af9244564f2370cdcc0a16325e91`; final diff review and the local
checkpoint remain pending.

## Final production-readiness continuation: 2026-10-24

Continued clean from `62234f9`; status **NOT READY**. Current scope and remaining
operator decisions are in [release evidence](V2_RELEASE_EVIDENCE.md).

| Check | Actual final result |
|---|---|
| Linux full backend + operational tools, final candidate-derived test image, new tmpfs PostgreSQL | **370 passed, 2 skipped, 1 XFAIL**, 98.60s; includes 356 backend + 14 backup-tool passes |
| Windows full backend + operational tools | **343 passed, 29 skipped, 1 XFAIL**, 79.40s; includes 329 backend + 14 backup-tool passes |
| Dedicated fresh PostgreSQL role/CLI integration | **4 passed**; migrations 0005→0006→0007, authenticated SQLAlchemy runtime/ownership/journal/heartbeat, 14 forbidden SQL operations, seeded unsafe column ACLs revoked, CLI error redaction/transaction rollback |
| Combined role-separated account/durable rehearsal | **32 browser passed**, seven fake SDK calls; encrypted local backup/restore of 9 pre-upgrade and 15 post-upgrade tables; synthetic legacy records preserved and explicitly assigned |
| Safe application rollback and TLS/session smoke | Actual prior account-aware image `v2-accounts-resume-review`, no app-source bind mount, production accounts + runtime role + durable off: preserved 15 table snapshots, owned task and committed journal; trusted HTTPS login/read/CSRF logout/revoked-cookie rejection and cookie security flags pass; page/ready 200, anonymous dashboard 401, docs 404 |
| Standalone encrypted PostgreSQL restore | PostgreSQL 16.15, 15 table snapshots equal, migration 0007, owner and account-readiness verified; authenticated encryption and local delivery; off-host false |
| Frontend checks | ESLint, application + test TypeScript, nine-file encoding check, Next 16.4.2 production build pass; npm audit **0 vulnerabilities** |
| Backend/static/dependencies | Ruff over backend/deploy/ops and pip check pass; final-image runtime inventory pip-audit **0 known vulnerabilities** |
| Image build/smoke | Independently tagged backend `v2-mission-review` rebuilt; runtime import, SDK/default inactive flags/CA trust pass; image preflight confirms both non-root users and healthchecks |
| Image security | Both final candidate fresh Scout scans: **1 HIGH / 0 CRITICAL**, CVE-2026-85091; gate exits 2, no suppression |
| Infrastructure/tooling | Combined production/accounts/role/limits Compose validates; synthetic resolved-config regression proves runtime/migration credential separation with shared env-file inheritance removed; Hadolint error threshold and actionlint pass; 30 PowerShell documentation blocks parse without execution |
| CI automation | Added dedicated PostgreSQL least-privilege and synthetic encrypted-backup restore jobs plus operational unit/static checks; hosted Actions not executed |
| Source security/checkpoint | Candidate files checked against configured real secrets and private-key/binary-artifact patterns; redacted Gitleaks candidate export and eight pre-checkpoint branch commits pass; intended source/tests/docs only selected for local checkpoint |

The Linux skips are the independently guarded least-privilege fixture integration,
which ran separately in a new named database with all four tests passing, and the
Docker Compose resolved-configuration test (CLI is absent inside the Linux test
image; its configuration-only test passed on Windows). Windows
also skips the 28 PostgreSQL durable/account cases exercised in the full Linux run.
The retained strict XFAIL is `test_timeout_stops_underlying_sdk_request`'s
documented synchronous SDK thread-cancellation limitation (see the exact test in
`test_gemini_responsiveness.py`); it is not hidden or counted as passing. Both full
runs retain 18 SQLite expression-index reflection warnings. No paid Gemini calls.

Ignored reproducible evidence:
`backups/v2-mission-final-{linux,windows}-tests.log`,
`backups/v2-mission-runtime-audit.json`,
`backups/v2-mission-image-{backend,frontend}/{summary.json,scout.sarif}`,
`backups/v2-encrypted-backup-evidence.json`, and
`backups/agentflow-v2-durable-e2e-accounts-20261024090218/report.json` plus
`frontend-tests.log`, and
`backups/agentflow-v2-durable-e2e-accounts-20261024091254/report.json` (rollback/TLS).
Final prior-image rollback/session evidence:
`backups/agentflow-v2-durable-e2e-accounts-20261024091807/report.json`.
New role/preflight/image/backup tests and guarded combined
harness are committed source; no archives or private evidence are staged.

TLS uses a newly generated synthetic CA trusted only by the verification SSLContext;
no system trust store or real TLS material changed. The test proxy drops all
capabilities then adds only NET_BIND_SERVICE, needed by the Caddy binary file
capability. Production cookie protocol was exercised with a trusted urllib cookie
client; actual-browser login/logout on the intended production ingress remains
unverified. The tested prior backend ID is
`sha256:feb37f9eda45aa450dce3ac8eb84ba039c6775c7914672a349a89146c23f3707`.
No claim extends to arbitrary older images or V1: never serve an owned database
through V1 bearer mode.

Full Linux tests bind current backend/deploy/ops source read-only into an image
derived from the final backend candidate, installing only constrained test tools.
The test container shares the network namespace of a newly created networkless
tmpfs PostgreSQL fixture. The final runtime inventory audit excludes editable app
metadata and build tools, as before. Constraints remain version pins, not hashes.

Production/development preservation compares the original five service container
IDs/start times/images/mounts and three real dotenv hashes; it does not read database
contents. All existing IDs and hashes remain unchanged. Only identified new test
fixtures are stopped; no Docker volumes are deleted. `main` remains
`6bd5b32b0d571370b5c4d2949870bd19a489ac14`, verified with `git rev-parse main`.

## Historical incomplete release candidate continuation: 2026-10-24

Preservation checkpoint: `09d55e9b8431e5cc463073843b68a9d30d0a63a8`, based on
`519fd72edc91ea1cf6de82b48595612e893c2c2d`. Exactly 38 reviewed files were committed
after configured-secret scanning, candidate-export Gitleaks and a 17-commit
history scan passed. Real dotenv files, backup archives, TLS material and ignored
operational evidence were excluded. The checkpoint explicitly says incomplete.

| Current validation | Actual result |
|---|---|
| Full Linux/Trixie backend, new tmpfs PostgreSQL | **319 passed, 1 XFAIL**, 45.87s; zero skips/failures |
| Full Windows backend | **291 passed, 28 PostgreSQL skips, 1 XFAIL**, 40.03s |
| Focused PostgreSQL accounts | **7 passed**, including three new subprocess crash cases |
| Combined account/durable browser rehearsal | **32 passed**, no skips/failures; seven fake SDK calls only |
| Frontend static/dependencies | ESLint, app and test TypeScript, nine-file UTF-8 check pass; npm audit zero vulnerabilities |
| Backend static/dependencies | Ruff and pip check pass; pip-audit of pinned final-image runtime inventory reports no known vulnerabilities |
| Configuration | Base, combined account+limits, durable-enabled and durable-disabled Compose validate without starting services; Hadolint error threshold and actionlint pass |
| Images | Both separate Trixie review image builds pass; no production tags selected |
| Runtime smoke | Non-root/read-only standalone frontend HTTP 200; SDK 2.31.0, legacy/durable-off defaults and system CA trust verified; both Debian libz hashes match |
| Operator syntax | 20 PowerShell blocks parse without execution |
| Image security | **BLOCKED**: one HIGH CVE-2026-85091 in each image, zero CRITICAL; source applicability investigation does not waive the finding |

Ignored current evidence: `backups/v2-final-linux-tests.log`,
`v2-final-windows-tests.log`, `v2-final-python-audit.json`, `v2-final-*.sarif` and
`agentflow-v2-durable-e2e-accounts-20261024065142/{report.json,frontend-tests.log}`.
The Python audit excludes editable application metadata and build tools; it uses
the installed runtime package inventory. Constraints are version pins, not hashes.
No hosted Actions or production acceptance result is claimed.

The three PostgreSQL account crash cases use `os._exit(23)` in a child process:
before provider dispatch, after one committed stage, and after task completion
before journal finalization. They revoke the owner's session before four competing
recovery workers run, prove recovery is idempotent, preserve owner/partial output/
token accounting, deny user B access/deletion, and return the existing journal
on A's same-key API retry. B's same key obtains a distinct scoped reservation.
No real provider adapter is invoked. Process fixtures validate an exact disposable
database identity and use new per-test PostgreSQL schemas.

The account browser regressions now cover login/reload/password/logout, service
failure, expiry, bad credentials/throttling, cross-tab logout and owner-switch
metadata clearing. The earlier self-broadcast reload loop is fixed. The initial
combined runtime fixture missed the browser's synthetic login cookie; sharing its
cookie context corrected that harness failure before the final 32-pass run.

Warnings: 18 SQLite expression-index reflection warnings; the preserved synchronous
Gemini cancellation XFAIL; harmless Node color-environment warnings. PostgreSQL
index/constraint behavior is covered separately. The zlib investigation and
limitations are in [V2_IMAGE_TRIAGE.md](V2_IMAGE_TRIAGE.md).

No existing database was migrated, restored or accessed by the fixture tests.
New fixtures use tmpfs and mount source read-only. No volumes were deleted or
modified by an operator command. Production/development container identities,
start times, image IDs and mounts plus real dotenv hashes are compared separately;
that preservation check is not a production database content-digest audit.
Final comparison passes for all five existing service containers and three real
dotenv files. Only newly created, identified fixtures are stopped; no volume is
deleted. Image scan command success means a report was produced, not a clean gate.

The current combined deployment contract is
[V2_ACCOUNTS_ROLLOUT.md](V2_ACCOUNTS_ROLLOUT.md) and its inactive
`deploy/compose.accounts.yml`. All following sections are historical evidence.

## Historical verification

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
