# Combined V2 release, rollback and emergency recovery

## Latest blocker status — 2026-10-24

Latest immutable image scans retain **1 HIGH / 0 CRITICAL** in each image for
CVE-2026-85091; risk remains unresolved and unaccepted. Encrypted 300 MiB
age/X25519 streaming and 15-table synthetic restore passed only with an isolated
local destination. Off-host storage, production schedules, key-custody continuity
and accepted recovery objectives remain unconfigured. PostgreSQL runtime-role
separation and ownership assignment are prepared and tested in isolation only;
the production read-only role audit found an overprivileged existing login at
revision 0005. No production role, migration or ownership change is authorized by
this runbook. See [release evidence](V2_RELEASE_EVIDENCE.md),
[role dry-run](V2_DATABASE_ROLE_DRY_RUN.md) and
[ownership mapping](V2_OWNERSHIP_ROLLOUT.md).

This runbook is prepared but inactive. It does not authorize deployment, changes
to existing roles/databases, legacy ownership assignment, or feature activation.
All preparation in this continuation used new synthetic fixtures. Keep the V1
deployment and its volumes intact until the operator accepts a controlled cutover.

## Current verified rehearsal scope

The account/durable browser harness ran on 2026-10-24 with new independently named
tmpfs PostgreSQL and backend containers, internal database networking, loopback
API ingress, read-only application mounts, non-root runtime, dropped capabilities
and the offline provider guard. **32 browser tests passed** and exactly seven fake
SDK calls were recorded. Evidence:
`backups/agentflow-v2-durable-e2e-accounts-20261024090218/report.json` and
`frontend-tests.log`. Only those newly identified fixtures were stopped.

The combined opt-in run additionally used actual separate migration and runtime
credentials. It migrated to 0005, seeded a synthetic V1 task/stage, encrypted and
restored its nine-table backup, then applied 0006 → 0007 preserving legacy rows.
It bootstrapped two accounts offline and explicitly assigned only that synthetic
legacy task to the selected synthetic administrator. Browser execution then ran
with `agentflow_runtime`; after completion, SELECT-only `agentflow_backup` created
an encrypted archive, the local destination adapter verified delivery, and restore
into a new database matched all **15 table snapshots** and migration ownership.
Keys/archives were temporary synthetic artifacts; off-host delivery was not claimed.

Separate least-privilege PostgreSQL tests exercise migrations 0005 → 0006 → 0007,
SQLAlchemy account/session/ownership and durable journal operations, denied DDL
and privilege escalation, and backup/restore. The read-only preflight passed
against that fixture as `agentflow_runtime`, confirming identity, revision 0007,
nonownership, restricted role/database/schema privileges and hardened search path.
These tests complement the earlier crash/recovery and synthetic legacy upgrade
tests. Real off-host disaster recovery and production HTTPS cookie acceptance
remain release gates until the operator's intended private ingress, credentials,
backup destination and encryption-key custody are exercised together.

Frontend lint, application/test TypeScript, nine-file encoding check, Next 16.4.2
production build and npm audit (zero findings) passed. Compose production +
accounts + role separation + limits validates with synthetic process-local inputs;
no service was started by configuration validation.

## Reproduce safe checks

PowerShell 5.1, from the repository root:

```powershell
# Offline by default: no service, database or dotenv file is selected.
.\backend\.venv\Scripts\python.exe deploy/release_preflight.py

# Image metadata inspection only; select the reviewed candidate tags/digests.
.\backend\.venv\Scripts\python.exe deploy/release_preflight.py --image agentflow-backend:v2-mission-review --image agentflow-frontend:v2-accounts-resume-review

# Existing guarded harness creates ONLY new synthetic fixtures; no paid calls.
Push-Location backend
try { .\.venv\Scripts\python.exe -m tests.verify_accounts_runtime } finally { Pop-Location }

# Complete synthetic role-separated, encrypted local-backup/restore rehearsal.
# Requires cryptography from ops/backup/requirements.txt in the invoking environment.
Push-Location backend
try { .\.venv\Scripts\python.exe -m tests.verify_accounts_runtime --least-privilege --backup-restore --https-smoke --image agentflow-backend:v2-mission-review } finally { Pop-Location }
```

For an authorized database inspection, load its URL into a process-scoped
environment variable through the operator's protected credential mechanism.
Never paste credentials into a recorded terminal, shell history or this document.
The following requires both expected database and expected connected runtime user;
the tool starts a read-only transaction and reports no connection string:

```powershell
.\backend\.venv\Scripts\python.exe deploy/release_preflight.py --database-env-var V2_PREFLIGHT_DATABASE_URL --expected-database agentflow --expected-user agentflow_runtime
```

`--env-file` is optional and explicit; configuration validation never loads a
dotenv file implicitly. Compose overrides and process environment can change the
effective configuration: inspect the selected overlays as well as the file.
Preflight is evidence collection, not release approval. It does not assert a clean
vulnerability scan, a verified backup, all grants, TLS acceptance, or production
readiness. Use the dedicated role tests, scanner gate and backup drill for those.

## Operator cutover sequence

1. Record the approved candidate commit, immutable image identifiers, vulnerability
   disposition, maintenance window, RPO/RTO and rollback threshold. Resolve every
   remaining HIGH/CRITICAL finding or obtain explicit documented risk acceptance.
   Do not suppress it solely to make a scanner pass.
2. Inventory the intended database/server/user/owners, current revision, row counts,
   old image identifiers, feature flags and active execution journals. Ensure no
   provider work is in flight before taking the recovery checkpoint. Unknown
   upstream outcomes require reconciliation, never automatic provider replay.
3. Generate an encrypted custom-format checkpoint using the designated backup
   credential. Verify archive readability, decryption, checksums, a restore into a
   separate database, and delivery to the real off-host destination. Demonstrate
   access to the separately held decryption key. A local copy is insufficient.
4. Review the SQL plan in [database role rollout](V2_DATABASE_ROLES.md). Create
   separately authenticated credentials through the operator's protected channel.
   Migration ownership/role changes require authorization; capture prior grants
   and ownership before applying. Never blindly revoke the sole recovery login.
5. Apply approved Alembic migrations with the migration credential while the old
   application is quiesced. Verify revision and the additive schema. Do not stamp
   around errors, downgrade irreversible revisions or proceed after failed DDL.
6. Bootstrap the chosen administrator offline. Export/review the ownership plan
   and obtain explicit record-to-owner approval before assignment. Unassigned
   legacy records remain quarantined. Preserve the reviewed manifest/audit.
7. Select the inactive `deploy/compose.accounts.yml`, `deploy/compose.roles.yml`
   and optional limits overlay. Set `V2_RUNTIME_DATABASE_URL` to the runtime
   credential and `V2_MIGRATION_DATABASE_URL` to the migration credential; the
   backend must never receive the latter. Validate Compose quietly; avoid
   `docker compose config` output that can expand secrets.
   The role overlay resets inherited `env_file` injection for backend/migrate:
   only explicitly declared environment keys from the reviewed base/overlays
   enter those containers. Declare optional runtime settings explicitly after
   review. Never inject migration, backup or operator credentials into the
   application environment; keeping two URL variables in a shared dotenv file
   must not grant both credentials to the runtime container.
8. Only after explicit deployment approval, perform the approved service change.
   Verify trusted HTTPS, health/readiness, anonymous denials, admin/member login,
   session/logout, owner-only listing and cross-user denial. Inspect effective
   auth/durable flags and runtime privileges. No paid provider smoke is implied.
9. Conduct a separately approved bounded provider acceptance if required, record
   spending and outcomes, then obtain final operator acceptance. Preserve the
   rollback checkpoint and both old images through the observation period.

## Application rollback

Trigger rollback for sustained readiness failure, unexpected authentication or
ownership behavior, loss of journal writes, elevated 5xx, failed backup checks or
an unacceptable security finding. Record the incident time and execution IDs.

Quiesce submissions through the approved ingress/maintenance procedure. Snapshot
the current state before rollback. Unknown paid outcomes must remain marked for
reconciliation. Retain `AUTH_MODE=accounts` and use a recorded known-good,
account-aware image. Durable activation can be disabled after execution drain;
account authorization and ownership enforcement must remain enabled. Never serve
an owned database through V1 legacy bearer mode, including on private ingress,
as the normal rollback path. V1-only recovery requires a NEW isolated clone of a
preownership backup, no traffic before reconciliation, and explicit operator
approval of the access model and recovery decision.

Keep schema/data intact; migration 0006/0007 downgrades intentionally refuse.
Application rollback is not permission to downgrade, drop tables, replace volumes,
reset ownership or restore over the live database. Re-run read-only schema,
privilege, health and private access acceptance checks before reopening ingress.

A fresh synthetic fixture verified the actual prior account-aware image
`agentflow-backend:v2-accounts-resume-review`, image ID
`sha256:feb37f9eda45aa450dce3ac8eb84ba039c6775c7914672a349a89146c23f3707`,
with **no application-source bind mount**, `APP_ENV=production`,
`AUTH_MODE=accounts`, runtime-role credentials and durable execution disabled.
The fixture used reviewed migration/test tooling mounts, while all backend
application code came from that image. Readiness passed, anonymous dashboard
access was denied, and all 15 table snapshots/ownership were preserved before
authentication smoke. Evidence:
`backups/agentflow-v2-durable-e2e-accounts-20261024091807/report.json`.

The rollback fixture preserved one committed owner-linked journal and one owned
task. An isolated Caddy proxy and production frontend image passed trusted
loopback HTTPS checks: `/` and `/api/ready` returned 200, anonymous
`/api/dashboard` returned 401, `/docs` returned 404, and security headers were
verified. A trusted HTTPS cookie client logged in, read `/api/auth/me` and the
authenticated dashboard, logged out with Origin/CSRF validation, and proved that
replaying the revoked session returns 401. The session cookie had the `__Host-`
prefix, Secure, HttpOnly, SameSite=Strict, Path=/, and no Domain. Auth activity
correctly changed synthetic session/audit state; owned task/stage/journal snapshots
remained unchanged afterward. Its synthetic CA was trusted only in a Python
SSLContext; no host trust store or production TLS storage changed.

This verifies this exact account-aware image's isolated rollback contract and
HTTPS cookie protocol. It does not prove V1 compatibility, acceptance of arbitrary
older images, or actual-browser cookie behavior on the operator's production
ingress. Reproduce without browser/provider work:

```powershell
Push-Location backend
try { .\.venv\Scripts\python.exe -m tests.verify_accounts_runtime --least-privilege --rollback-only --https-smoke --image agentflow-backend:v2-accounts-resume-review } finally { Pop-Location }
```

Add `--https-smoke` for the isolated proxy checks. The official Caddy image needs
only `NET_BIND_SERVICE` added back after dropping all capabilities because its
binary has that file capability; no application container gains it. The synthetic
proxy uses tmpfs TLS/config state and disables automatic trust installation.
Docker Desktop tmpfs certificate export uses `docker exec cat` for the public CA
certificate, since `docker cp` could not read that mount. These fixture issues
were corrected before the final successful TLS smoke.

## Emergency backup recovery

Preserve the failed database and collect the last known backup manifest, checksum,
key identifier, candidate revision and image identifiers. Retrieve/decrypt with
separate credentials into protected temporary storage. Verify authenticated
decryption and archive integrity before restoration.

Restore into a NEW isolated PostgreSQL 16 instance/database with no public ingress.
Recreate the reviewed roles; restore schema objects with their intended migration
owner; apply reviewed runtime/backup grants. Compare Alembic revision, table counts,
representative synthetic/application records, owner links, sessions and journal
states against the backup manifest. Account session invalidation and post-backup
provider outcomes require operator reconciliation. A stale backup may lose
idempotency keys: never auto-submit paid work because its key disappeared.

Prove trusted private HTTPS and owner isolation on the recovered candidate before
the operator approves any connection switch. Record actual recovery duration and
data-loss interval against RTO/RPO. Restore drills here do not prove recovery of
external provider side effects, off-host availability or key-custody continuity.

## Observation and post-release monitoring

At cutover, 5 minutes, 30 minutes, 24 hours and each backup cycle, record health,
readiness, image IDs, revision, effective flags, authentication failures/throttling,
5xx, request latency, journal lease/heartbeat age, interrupted/unknown outcomes,
database connections/capacity and encrypted backup age/integrity/delivery status.
Use structured request IDs and journal IDs; exclude prompts, cookies, passwords,
provider keys and connection strings from monitoring exports. Reconcile duplicate
submission/unknown-outcome incidents before retrying. Route alerts through the
operator-configured monitor; no messaging destination is provisioned by this work.

Require a recovery drill after key rotation, PostgreSQL upgrade, backup adapter or
role-grant changes, and at the operator's accepted periodic interval. Retain
backup access and prior images until rollback acceptance expires. No automatic
production deployment or destructive recovery command is included in this runbook.
