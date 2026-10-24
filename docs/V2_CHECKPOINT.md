# V2 development checkpoint

## Latest continuation: 2026-10-24

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
