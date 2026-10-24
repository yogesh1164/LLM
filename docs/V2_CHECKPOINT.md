# V2 development checkpoint

## Current production-readiness continuation: 2026-10-24

Continued from `62234f9` on `feature/v2-production-hardening`. Current engineering
estimate **95% complete / 5% remaining**; release status **NOT READY**. Implemented
and verified isolated least-privilege PostgreSQL roles, encrypted synthetic
backup/restore, combined role-separated account/durable rehearsal, fail-closed
preflight/image tooling and CI operational checks. Fixed account-mode rate-limit
double counting and production error handling. See
[current evidence and remaining approvals](V2_RELEASE_EVIDENCE.md) and
[final validation results](V2_VERIFICATION.md).

Both final app image scans retain **1 HIGH / 0 CRITICAL**, CVE-2026-85091. No
supported Trixie patch was available; no suppression or risk acceptance is enabled.
Off-host destination/key custody, production role rollout, legacy assignment,
maintenance/cutover, feature activation and final acceptance remain operator gates.
No production/development DB changes, real environment overwrites, service restarts,
volume deletions, paid Gemini requests, push, merge or deployment occurred.

Older snapshots below retain their original counts and limits as historical evidence;
they do not supersede the current evidence/runbooks.

## Historical incomplete release candidate: 2026-10-24

Preserved all 38 original modified/untracked files in local checkpoint
`09d55e9b8431e5cc463073843b68a9d30d0a63a8` after candidate and history secret scans.
No production-ready claim, push, merge, deployment or production activation.
Continuation adds real PostgreSQL account-aware subprocess crash/recovery tests,
zlib source applicability evidence, final local validation and an inactive combined
account/durable deployment overlay. See [verification](V2_VERIFICATION.md).

Current results: Linux/Trixie **319 passed / 1 XFAIL**; Windows **291 passed /
28 PostgreSQL skips / 1 XFAIL**; combined browser **32 passed**. Final image scans
remain **one HIGH per image, zero CRITICAL**. This supersedes older 9/8 counts.
The main route/account/frontend implementation is complete and tested locally.
Never rerun completed development or synthetic restore drills merely to resume.

Remaining release gates:

1. Vendor-supported zlib remediation or separately accepted applicability review;
   no scanner suppression or security waiver has been enabled.
2. Production runtime database least privilege and encrypted off-host backup/key
   custody/retention acceptance; these operational changes remain unauthorized.
3. Explicit legacy ownership, maintenance/cutover and recovery decisions; private
   HTTPS account acceptance and hosted CI have not been executed for this release.
4. Known synchronous Gemini cancellation/unknown upstream outcomes, single-process
   admission and lack of distributed spending budgets remain documented limits.

Effort-weighted readiness estimate: **92% complete, 8% remaining**, using durable
15%, accounts 25%, image security 15%, combined integration 20%, final checks 10%,
rollout docs 10%, review/checkpoint 5%. This is an engineering estimate, not a test
pass percentage or production approval. Production readiness remains **NOT READY**.
The component estimates are 90%, 95%, 85%, 95%, 90%, 90%, 95% respectively;
their weighted sum is 91.75%, rounded to 92%. Vendor waiting and production
operational changes are not counted as completed by local functional tests.
All following sections retain historical context and do not supersede this status.

## Historical checkpoints

## Completed isolated integration: 2026-10-24

Resumed clean from `259624a` on `feature/v2-production-hardening`. Frontend key
lifecycle, duplicate/202/409 handling, bounded monitoring and restored partial
results now cover fixed/SSE, custom-agent and custom-workflow execution. No prompts
or credentials were added to submission metadata. Playwright mocked/browser tests
and browser-to-enabled-backend checks pass. Backend schema verification is read-only.

0006 is unchanged and verified on disposable PostgreSQL: all legacy history,
constraints, repeat upgrade, transactional DDL failure and refused downgrade.
The process-level drill passed ten groups, including four abrupt-crash points,
heartbeat expiry, stale writes, two-process duplicate admission, browser integration
and a binary-safe synthetic backup/restore with matching hashes/table digests.

Final backend: Linux **269 passed / 1 XFAIL**; Windows **248 passed / 21 PostgreSQL
skips / 1 XFAIL**. Frontend integrated fixture run: **26 passed**, including 23
mocked/client/browser cases plus three real offline-runtime browser cases.
See V2_VERIFICATION.md for evidence, checks and limitations.

Operator-ready [rollout/rollback](V2_DURABLE_ROLLOUT.md), opt-in/disabled Compose
overlays and safe private HTTPS checks are prepared, not executed against V1.
Keep production durable mode off. Existing DBs/volumes, production configuration,
dotenv files and main are preserved. No push, merge, production migration or deploy.
Image high findings remain a release gate; approval is required before production
migration/activation. Paid smoke tests remain separately approval-gated.

## Durable execution continuation: 2026-10-24

Resumed from `89958d4` on `feature/v2-production-hardening`, initially clean.
Implemented an opt-in execution journal, database leases, guarded state writes,
one-use idempotency keys and startup/periodic interruption detection. Recovery
preserves committed stage outputs/token usage and never reruns provider work.
See [V2_DURABLE_EXECUTION.md](V2_DURABLE_EXECUTION.md) for guarantees and limits.

- Additive `0006_durable_executions` creates only a new table/index. Migrations
  were exercised on isolated SQLite and temporary PostgreSQL schemas only.
- All paid routes (fixed/SSE/custom workflow/custom agent) are wrapped when enabled.
  Synchronous Gemini and its cancellation XFAIL remain. Durable calls disable
  automatic application retries. Same-key repeats never restart execution.
- `DURABLE_EXECUTION_ENABLED` defaults false; `.env`/`.env.production` unchanged.
  Current frontend does not yet supply durable keys or handle duplicate 202s.
  Keep disabled for the existing deployment pending API/UI rollout review.
- No users, ownership/backfill, credential/role changes, existing DB writes, image
  deployment, push, merge or GitHub-main operations. Local `main` stays `6bd5b32`.
- Latest full results and the exact candidate-file inventory are in V2_VERIFICATION.md.
  The known image release gate remains: last review scans 9 backend / 8 frontend
  high findings, zero critical; no new image scan or suppression in this continuation.

Next work: review/rehearse the enabled API/UI key lifecycle and migration on an
isolated target, then consider a separately approved rollout. Do not treat
`safe_to_resubmit` as permission to automatically retry with a new key. Unknown
provider outcomes and unjournaled legacy crash records require reconciliation.

## Earlier request-limit continuation: 2026-10-24


Verified branch `feature/v2-production-hardening` and commits `fbb4915`, `8caf560`,
`bc9abdc` before changes. The worktree already contained unfinished Docker helper,
request-budget and interruption-test changes; reviewed and completed these locally.
`main` remains `6bd5b32`. No push, merge, deployment or account/ownership migration.

- API bodies now default to a 256 KiB cap before parsing/endpoint side effects,
  including undeclared/chunked input. Malformed/duplicate lengths are rejected.
  Non-ASCII bearer input returns 401 instead of a comparison exception.
- Progress interruptions close newly started stages and preserve already committed
  stage outputs, status and token accounting. No Gemini rewrite or paid calls.
- Added cancellation/timeout/capacity interruption tests and a subprocess crash
  fixture proving committed history survives without implicit provider replay.
  Crashed work still remains `running`; durable jobs/leases are not implemented.
- Both Docker runtime stages strip setuid/setgid regular-file bits. Root inspection
  confirms none remain; actual application users stay non-root. Package metadata
  remains intact. See [image triage](V2_IMAGE_TRIAGE.md): mitigations do not patch
  the unresolved Debian packages or clear the image release gate.
- Full backend suite: **217 passed, 1 XFAIL** on Windows and in the isolated Linux
  review image. Ruff, pip check, frontend lint/TypeScript/encoding/build, Compose
  validation, Dockerfile lint and redacted Git-history scanning pass.
- Separate `v2-review-hardening` app images rebuilt; no production tags replaced.
  Backend Scout still reports **9 high findings**; frontend reports **8**.
  Full verification/evidence details are in V2_VERIFICATION.md.

The approval gate below is unchanged. Next safe work is supported image-component
remediation, then isolated durable-job design/tests. Do not auto-replay unknown
provider outcomes or activate multi-user mode. Do not rerun restore drills.

## Original checkpoint: 2026-10-23

Read this file, V2_SECURITY_AUDIT.md, V2_ARCHITECTURE.md and V2_VERIFICATION.md
before further work. This checkpoint was requested by the operator to stop safely.

## Preserved state

- Worktree: `C:\seamdigitech\LLM`; branch `feature/v2-production-hardening`.
- Base main revision `6bd5b32`; main was clean and synchronized with origin.
- Local focused checkpoint commits are authorized; **no push or merge authorized**.
  Use `git log --oneline main..HEAD` for their exact hashes.
- Production remains the V1 private deployment at `https://localhost:8443`.
  Review images use separate tags `agentflow-backend:v2-review` and
  `agentflow-frontend:v2-review`; they are not deployed.
- Preserve `llm-postgres-1` / `llm_agentflow-postgres` and
  `agentflow-private-postgres-1` / `agentflow-private_postgres-data`.
  No production/development database writes occurred in V2 work.
- Preserve earlier retained restore-drill container/databases and ignored backups.
- `.env` and `.env.production` were not overwritten. Never print their contents.
- No new live Gemini calls; SDK 2.31.0 and production model
  `gemini-3.5-flash-lite` preserved. The application fallback default differs;
  production Compose explicitly fixes the working model. Do not change models
  or run paid calls merely to continue this checkpoint.

## Completed

Audit and route/data mapping; offline tests of all sensitive route authentication;
inactive Argon2id, cookie, session expiry, CSRF and role/owner primitives; bounded
Gemini worker admission surviving caller cancellation; custom-agent cancellation
persistence; JSON telemetry/request IDs; safe Markdown images/citations and error
boundary; CI/security jobs; dependency advisory fixes; tested Linux dependency
constraints and app base-image digest pins; optional resource-limit overlay.

Final suite: 183 passed, one existing expected failure. Ruff, ESLint, TypeScript,
frontend build, Compose validation and static workflow/Dockerfile checks passed.
Image scans still fail on high Debian advisories; see verification report.

## Approval gate still pending

An unanswered operator decision was presented: use invite-only accounts and map
legacy records to an explicitly selected Admin, or leave legacy records unassigned
and quarantined. **No approval has been inferred.** Account routes, user tables,
ownership/backfill migrations and multi-user frontend are not implemented/enabled.
Do not activate accounts before every ownership boundary is enforced. Do not
assign records to a first registrant or silently disable the bearer mode.

## Next safe sequence

1. Verify branch, clean tree and checkpoint commits; inspect any new operator changes.
2. Review the image advisories and obtain a supported patch/reachability plan;
   no blanket scanner suppression or untested distro migration.
3. Resolve the legacy ownership/account migration decision. Implement reviewed
   users/sessions/invites/nullable ownership migration only on isolated fixtures;
   add PostgreSQL A/B access, login-rate-limit, CSRF and migration tests.
4. Implement idempotency/leases/recovery following the design; never auto-replay
   unknown-outcome paid calls. Retain the cancellation XFAIL.
5. Finish cookie-authenticated frontend/profile/logout after API isolation is proven.
6. Review runtime DB role separation, off-host encryption/retention and RPO/RTO
   with the operator. Do not rotate credentials or alter privileges automatically.
7. Push/draft PR only after fresh explicit permission. No merge or public deployment.

Do not rerun completed database restore drills, restart production or repeat paid
Gemini smoke tests merely to recover context. Re-run tests only for new changes or
an unresolved concern. Remote GitHub Actions have not run yet.

## Useful commands (Windows PowerShell 5.1)

```powershell
Set-Location C:\seamdigitech\LLM
git status --short --branch
git log --oneline main..HEAD
git diff main...HEAD --stat

Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check app tests
Set-Location ..\frontend
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd run build
Set-Location ..

$dockerCli = 'C:\Users\dhanu\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $dockerCli --context desktop-linux compose -p agentflow-private -f compose.production.yml --env-file .env.production config --quiet
```

Host Docker/pytest temp access may require approved host execution; sandbox
`CodexSandboxOffline` restrictions do not mean Docker is uninstalled. Never use
PowerShell `>` for binary dumps; retain the documented in-container dump + copy
procedure. Never remove volumes, restore over an existing database, or alter main.

Suggested eventual draft PR: **Add V2 security and execution foundations**.
Describe inactive auth/migration gates and failing image-security findings explicitly;
do not label the checkpoint a completed V2 release.
