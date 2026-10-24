# Account and durable execution production preparation

Latest preparation: use the [combined release/rollback runbook](V2_COMBINED_RELEASE_RUNBOOK.md)
with the [separate database-role rollout](V2_DATABASE_ROLES.md) and
[encrypted backup/recovery](V2_ENCRYPTED_BACKUP_RUNBOOK.md). Role-separated runtime
and synthetic account/durable browser acceptance now pass in isolation. The
inactive `deploy/compose.roles.yml` overrides runtime/migration URLs separately;
no existing connection, credential or feature flag was changed. Current image
and operator gates are listed in [release evidence](V2_RELEASE_EVIDENCE.md).

Status, 2026-10-24: implemented and tested in isolation; not deployed. This
procedure does not authorize a production migration, environment edit or cutover.
Keep existing databases, volumes, credentials and the V1 service unchanged.

## Implemented contract

`AUTH_MODE` defaults to `legacy_bearer`. Explicit `accounts` mode rejects bearer
fallback. There is no registration, invitation or password-reset HTTP API.
An operator creates accounts through `python -m app.account_operator`; passwords
are read twice from an interactive terminal, never from arguments or files.
Administrators do not have access to other members' content.

Production sessions use `__Host-agentflow_session`, Secure, HttpOnly,
SameSite=Strict, Path=/ and no Domain. Development uses `agentflow_session_dev`
without Secure. Absolute lifetime is 12 hours and idle lifetime 30 minutes.
Only session/CSRF digests are stored. Login rotates the presented session;
password change/reset and disable revoke all sessions for that account.
Mutations require exact allowed Origin and session-bound `X-CSRF-Token`.
Login requires exact Origin and `X-AgentFlow-Login: 1`. This custom-header check
replaces the earlier proposed pre-auth session design. Shared database admission
allows five attempts per normalized login and 60 globally per five minutes;
two concurrent password hashing operations are admitted per process.

The browser keeps CSRF in memory and uses cookies for authentication. It removes
the legacy token on entry to account mode, unmounts private content after 401,
and notifies other tabs of identity changes without reloading the sending tab.
Non-secret, owner-tagged execution metadata can survive sign-out for recovery;
a different account clears it before mounting its workspace. Recovery never
automatically resubmits a potentially billed operation.

## Migration and ownership review

For legacy records belonging to multiple accounts, use the reviewed
[component mapping and quarantine procedure](V2_OWNERSHIP_ROLLOUT.md), not a
single-workspace owner assignment. The older `assign-ownership` command now also
requires `--confirm-manifest-digest EXACT_APPROVED_MANIFEST_DIGEST`; confirm it
against the manifest and never include a real password in command arguments.
Synthetic mapping and quarantine tests passed; no real production records were
inventoried for assignment or changed.

`0007_accounts_ownership` follows `0006_durable_executions`. It adds users,
sessions, login buckets, account audit, ownership-assignment audit and nullable
indexed owner foreign keys on tasks, agents, agent executions, workflows,
workflow runs and durable journals. Stage/step access derives from parents.
Agent names are unique per owner; null legacy owners retain a separate unique
index. Existing data stays unassigned and invisible in account mode. The
migration never selects an owner or creates a user. Downgrade refuses data loss.

Before an approved cutover, rehearse on a newly restored isolated target:

1. Record source database identity, revision, image IDs, row counts and fresh
   binary-safe backup evidence. Resolve unfinished/unknown provider outcomes.
2. Apply the explicitly reviewed revision `0007_accounts_ownership`. Do not use
   an unreviewed `upgrade head`: head now includes account/ownership changes.
3. Bootstrap the explicitly selected administrator through the interactive CLI.
   All commands require `--expect-database DATABASE_NAME`; mutations require an
   approval reference. Bootstrap refuses a nonempty account table.
4. Either retain null ownership in quarantine, or obtain approval for a specific
   whole-workspace assignment. `plan-ownership --owner-id UUID --output FILE`
   creates a new manifest containing IDs/counts/digests. Review it before
   `assign-ownership --manifest FILE --confirm-login LOGIN --approval REF --confirm-manifest-digest EXACT_APPROVED_MANIFEST_DIGEST --apply`.
   No `--apply` means no assignment. Stale/tampered manifests, foreign references,
   running executions and a non-admin target are refused. Assignment is atomic
   and a repeat of the identical manifest verifies ownership and returns zero.
5. Add members using `add-member --login LOGIN --approval REF`. Confirm A/B/Admin
   isolation for list/detail/mutation/history, nested references, journal status
   and same-key durable retries. Review production HTTPS cookie and Origin checks.
6. Enable accounts only in separately approved deployment configuration. Current
   Compose retains its required legacy token interpolation; account middleware
   ignores that bearer. Configuration preparation/secret changes are a future
   operator step. Do not weaken the base Compose guard to bypass configuration.

Readiness requires PostgreSQL in production, revision 0007, an enabled admin,
owner columns, consistent resource relationships and owner/journal scopes.
Legacy mode refuses startup once owned content exists. Do not run old unrestricted
bearer code against account data or keep a second legacy route into that database.

## Combined operator sequence (prepared, not executed)

The following commands are for an approved maintenance window only. The image
security gate must be cleared first. Rehearse against a new isolated restored
target before changing the existing deployment. Use PowerShell 5.1; stop on every
nonzero exit code. Do not print resolved Compose configuration or dotenv contents.

1. Record the release commit and immutable image IDs, source database/container
   identity, Alembic revision, row counts, volume mounts and outstanding execution
   reconciliation. Confirm the target is the private `agentflow-private` stack,
   never the `llm` development stack. Record an explicit approved legacy owner or
   the decision to retain null ownership in quarantine.
2. Use the binary-safe backup, checksum/archive validation and fresh isolated
   restore procedure in section A.3 of [the durable runbook](V2_DURABLE_ROLLOUT.md).
   Do not execute its section A.4 (the separate durable-only migration).
   Check source revision independently: it may be 0005 or 0006 before cutover.
   Preserve the original volume and archive. Do not restore over either existing
   database. Confirm encrypted off-host copy, key custody, retention and measured
   restore acceptance before calling backup operations production-ready.
3. Prepare the reviewed image references and validate the inactive overlay:

```powershell
$dockerCli = 'C:\Users\dhanu\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
# Replace these with the independently approved immutable sha256 image IDs.
$env:V2_BACKEND_IMAGE = 'sha256:REVIEWED_BACKEND_IMAGE_ID'
$env:V2_FRONTEND_IMAGE = 'sha256:REVIEWED_FRONTEND_IMAGE_ID'
$accountCompose = @('--context','desktop-linux','compose','-p','agentflow-private',
  '-f','compose.production.yml','-f','deploy/compose.accounts.yml',
  '--env-file','.env.production')
& $dockerCli @accountCompose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Combined configuration validation failed' }
```

4. In the approved write freeze, stop application traffic/workers and reconcile
   running journals before ownership planning. Never run old bearer code against
   newly owned data. Take the final approved backup after draining writes. Apply
   the explicit revision and bootstrap the named administrator interactively:

```powershell
& $dockerCli @accountCompose stop backend frontend
if ($LASTEXITCODE -ne 0) { throw 'Application drain/stop failed' }
# Take and validate the final binary-safe backup before the next command.
& $dockerCli @accountCompose run --rm --no-deps migrate
if ($LASTEXITCODE -ne 0) { throw 'Account migration failed; do not stamp or downgrade' }
& $dockerCli @accountCompose run --rm --no-deps migrate python -m app.account_operator `
  --expect-database agentflow bootstrap --login APPROVED_ADMIN --approval APPROVAL_REFERENCE
if ($LASTEXITCODE -ne 0) { throw 'Administrator bootstrap failed' }
```

   Password input requires an interactive terminal: do not use `-T`, argv secrets,
   pipelines or environment passwords. Existing account tables make bootstrap
   refuse; use the reviewed recovery procedure rather than bypassing that check.
5. If legacy assignment is approved, plan and export the manifest while writes
   remain frozen, review its owner/IDs/counts/digests, then apply in one transaction.
   The operator must provide a private bind-mounted directory for the manifest:
   the runtime root is read-only. For example, prepend
   `run --rm --no-deps -v APPROVED_ABSOLUTE_DIRECTORY:/review migrate` and use
   `/review/ownership.json` for CLI `--output`/`--manifest` paths. Do not place
   this file in Git. Without approved assignment, null data remains quarantined.
6. Verify schema/readiness and ownership consistency; start exactly one reviewed
   accounts backend and frontend using the combined overlay. Add members through
   the interactive operator command. Check private HTTPS, secure cookie flags,
   login/logout/password change, A/B/Admin access boundaries, CSRF failures,
   same-key 202/409 behavior, refresh/status monitoring, and read-only partial
   output recovery. Paid smoke tests require separate explicit approval.

```powershell
& $dockerCli @accountCompose run --rm --no-deps migrate python -m app.verify_durable_schema
if ($LASTEXITCODE -ne 0) { throw 'Schema verification failed' }
& $dockerCli @accountCompose run --rm --no-deps -e AUTH_MODE=accounts migrate python -c 'from app.ownership import verify_account_readiness; verify_account_readiness()'
if ($LASTEXITCODE -ne 0) { throw 'Account readiness failed' }
& $dockerCli @accountCompose up -d --no-deps --no-build backend frontend
if ($LASTEXITCODE -ne 0) { throw 'Application activation failed; keep traffic closed' }
& $dockerCli @accountCompose ps
if ($LASTEXITCODE -ne 0) { throw 'Inspect application status before acceptance' }
```

   The existing bearer-only `deploy/check_private_health.py` is for the durable
   legacy rollout. It is not an account acceptance check: use a browser session
   on the exact configured HTTPS origin and the A/B checklist above. Never put a
   session cookie in a command-line argument or use `--insecure` to bypass trust.
7. Record acceptance, image IDs and release commit. Keep the public/private
   listener policy unchanged. Do not enable replicas until distributed spending
   and admission budgets are separately designed and tested.

## Rollback decision points

Before any ownership writes, a migration failure should leave PostgreSQL DDL and
revision transactional; verify, do not assume. Keep traffic stopped and investigate.
After ownership or new account data exists, old V1 bearer rollback is unsafe.
Do not use the durable-only disabled overlay to bypass account isolation.
Keep account authorization enabled when disabling durable execution, and reconcile
running/unknown-outcome jobs before any feature transition.

Do not downgrade 0007, remove owners, stamp revisions or overwrite an existing
database. Retain the original target; restore an approved backup into a new
isolated target, reconcile post-cutover writes, and review which code can read it
safely before any traffic switch. Durable-only rollout remains separately
documented in [V2_DURABLE_ROLLOUT.md](V2_DURABLE_ROLLOUT.md), pinned to revision 0006.

Release remains blocked by the image high-severity gate, production ownership and
cutover decisions, runtime DB role separation, encrypted off-host backup/key
custody/retention, and operational acceptance. Keep one worker/replica; provider
admission and execution rate limits are not distributed account spending budgets.
The synchronous Gemini cancellation XFAIL still describes possible upstream cost.
Remote CI/branch protection and production HTTPS isolation checks require future
operator execution. Passing local tests does not authorize deployment.

## Repeatable offline verification

From `backend`, run `.\.venv\Scripts\python.exe -m tests.verify_accounts_runtime`.
The harness creates only fresh tmpfs PostgreSQL and separate review API containers,
mounts source read-only, uses the guarded fake provider, and runs all frontend
tests including three actual account/durable browser paths. It stops only its own
identified containers and leaves ignored evidence under `backups`. No restore,
existing volume, real dotenv file or paid API is used. Other PostgreSQL tests
require the strictly validated `DURABLE_TEST_DATABASE_URL` fixture identity.
