# Private durable-execution rollout and rollback

Current-source note: Alembic head is now `0007_accounts_ownership`. This durable-only
procedure deliberately pins `0006_durable_executions`; do not replace it with
`upgrade head`. Account cutover requires the separate
[account review procedure](V2_ACCOUNTS_ROLLOUT.md) and production approval.

**Approval boundary:** this is an operator procedure, not authorization to execute
it. No existing development/production database was migrated or activated during
development. Obtain explicit approval for the maintenance window, production DB
identity, reviewed image IDs, migration 0006, opt-in overlay and recovery plan.
The unresolved image-security gate also requires remediation/review before release;
passing functional tests is not a release-security waiver. No paid smoke call is
included. Do not push/merge as part of this procedure.

## Exact impact

0006 follows `0005_custom_workflows`. It adds `durable_executions` (15 columns),
primary key `id`, unique `(scope,key_digest)` plus three unique target links, three
nullable `ON DELETE SET NULL` foreign keys, two checks (valid states/at most one
target), and the `(state,lease_expires_at)` index. No legacy columns, ownership,
records or roles are backfilled/changed by the migration. Empty target links are
valid reservations; dangling non-null links are prohibited. PostgreSQL DDL and the
Alembic revision update are transactional. Reapplying the upgrade is a no-op.
Downgrade deliberately refuses to delete journal tombstones; do not stamp past a
failure or drop the table to make rollback appear successful.

The opt-in overlay changes only the backend/frontend/migration image selection and
the backend feature flag. PostgreSQL, Caddy, credentials, model, private port binding,
volumes and networks remain as in the base file. The migration service flag stays
off because migration is explicit, not an application startup side effect.

## A. Safe private rollout (only after approval)

Run in **Windows PowerShell 5.1**, at the project root. Every Docker command below
targets `desktop-linux` and `agentflow-private` explicitly. Check `$LASTEXITCODE`
after every command; stop immediately on failure. Never print a resolved Compose
configuration or container environment. Do not edit either real dotenv file.

### 1. Select reviewed images and confirm identity

```powershell
Set-Location C:\seamdigitech\LLM
$ErrorActionPreference = 'Stop'
$dockerCli = 'C:\Users\dhanu\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
if ((git branch --show-current) -ne 'feature/v2-production-hardening') { throw 'Wrong branch' }
git status --short --branch
git rev-parse HEAD
git rev-parse main

# Use the exact independently built/reviewed image IDs from the release record.
# Do not rebuild or retag the stable :local images.
$releaseStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$env:V2_BACKEND_IMAGE = "agentflow-backend:v2-approved-$releaseStamp"
$env:V2_FRONTEND_IMAGE = "agentflow-frontend:v2-approved-$releaseStamp"
$reviewBackendId = & $dockerCli --context desktop-linux image inspect agentflow-backend:v2-completion-review --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Review backend image missing' }
$reviewFrontendId = & $dockerCli --context desktop-linux image inspect agentflow-frontend:v2-completion-review --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Review frontend image missing' }
# Compare these IDs to the approved release evidence before continuing.
& $dockerCli --context desktop-linux image tag $reviewBackendId $env:V2_BACKEND_IMAGE
if ($LASTEXITCODE -ne 0) { throw 'Backend tagging failed' }
& $dockerCli --context desktop-linux image tag $reviewFrontendId $env:V2_FRONTEND_IMAGE
if ($LASTEXITCODE -ne 0) { throw 'Frontend tagging failed' }

$base = @('--context','desktop-linux','compose','-p','agentflow-private','-f','compose.production.yml','--env-file','.env.production')
$v2 = @('--context','desktop-linux','compose','-p','agentflow-private','-f','compose.production.yml','-f','deploy/compose.durable.yml','--env-file','.env.production')
$disabled = @('--context','desktop-linux','compose','-p','agentflow-private','-f','compose.production.yml','-f','deploy/compose.durable.yml','-f','deploy/compose.durable-disabled.yml','--env-file','.env.production')
& $dockerCli @v2 config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Opt-in Compose validation failed' }
& $dockerCli @disabled config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Rollback Compose validation failed' }

$productionDbId = & $dockerCli @base ps -q postgres
if (!$productionDbId) { throw 'Production DB is not running' }
& $dockerCli --context desktop-linux inspect $productionDbId --format '{{.Id}}|{{.Name}}|{{.State.StartedAt}}|{{range .Mounts}}{{.Name}}:{{.Destination}}{{end}}'
# REQUIRE agentflow-private-postgres-1 and agentflow-private_postgres-data.
# STOP if llm_agentflow-postgres or another mount appears.
& $dockerCli @base exec -T postgres psql -U agentflow -d agentflow -v ON_ERROR_STOP=1 -c 'SELECT current_database(), current_user, current_schema();' -c 'SHOW server_version;' -c 'SELECT system_identifier FROM pg_control_system();' -c 'SELECT version_num FROM alembic_version;'
if ($LASTEXITCODE -ne 0) { throw 'Database identity check failed' }
# REQUIRE database/user agentflow, PostgreSQL 16 and expected revision 0005 (or already verified 0006).
.\backend\.venv\Scripts\python.exe deploy/check_private_health.py --mode v1
if ($LASTEXITCODE -ne 0) { throw 'V1 HTTPS health/auth checks failed' }
```

Record the DB system identifier, mount name, container ID/start time, revision,
approved Git SHA, reviewed image IDs and the current backend/frontend image IDs.
Retain unique rollback tags for the current image IDs using `docker image tag`.
Inspect only `.Image` and specific labels/mounts; never dump `.Config.Env`.

### 2. Maintenance and drain

Stop incoming private traffic first; keep the backend available while existing work
drains. Notify authorized operators and prevent alternate internal API callers.

```powershell
& $dockerCli @base stop proxy
if ($LASTEXITCODE -ne 0) { throw 'Could not suspend private traffic' }
& $dockerCli @base exec -T postgres psql -U agentflow -d agentflow -v ON_ERROR_STOP=1 -c "SELECT 'tasks' AS kind,count(*) FROM tasks WHERE status IN ('pending','running') UNION ALL SELECT 'agents',count(*) FROM custom_agent_executions WHERE status IN ('pending','running') UNION ALL SELECT 'workflows',count(*) FROM custom_workflow_runs WHERE status IN ('pending','running');"
if ($LASTEXITCODE -ne 0) { throw 'Drain inventory failed' }
# Continue only after live work is drained. Nonzero legacy orphan records require
# operator reconciliation; do not bulk-change/delete them to satisfy this gate.
& $dockerCli @base stop frontend backend
if ($LASTEXITCODE -ne 0) { throw 'App stop failed' }
```

Stopping a process cannot cancel an already dispatched synchronous provider request
at the provider. Resolve any ambiguous outstanding calls before resubmission.

### 3. Binary-safe backup and validation

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$backupName = "agentflow-pre-0006-$releaseStamp.dump"
$backupPath = Join-Path (Resolve-Path backups) $backupName
if (Test-Path -LiteralPath $backupPath) { throw 'Refusing to overwrite backup' }
$contentTables = @('tasks','agent_executions','custom_agents','custom_agent_executions','custom_workflows','custom_workflow_steps','custom_workflow_runs','custom_workflow_step_runs')
$sourceRevision = & $dockerCli @base exec -T postgres psql -U agentflow -d agentflow -At -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version;'
if ($LASTEXITCODE -ne 0) { throw 'Cannot record source revision' }
if ($sourceRevision -eq '0006_durable_executions') { $contentTables += 'durable_executions' }
elseif ($sourceRevision -ne '0005_custom_workflows') { throw 'Unexpected source revision' }
$sourceManifest = @{}
foreach ($table in $contentTables) {
    $digestSql = "SET TIME ZONE 'UTC'; SELECT count(*)::text || ':' || coalesce(md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id)), '') FROM $table t;"
    $digestLines = & $dockerCli @base exec -T postgres psql -U agentflow -d agentflow -At -v ON_ERROR_STOP=1 -c $digestSql
    if ($LASTEXITCODE -ne 0) { throw 'Source content manifest failed' }
    $sourceManifest[$table] = ($digestLines | Select-Object -Last 1)
}
$sourceManifest | ConvertTo-Json | Out-File -LiteralPath ($backupPath + '.manifest.json') -Encoding utf8
& $dockerCli @base exec -T postgres pg_dump -U agentflow -d agentflow --format=custom --no-owner --no-acl --file /tmp/$backupName
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
& $dockerCli @base exec -T postgres pg_restore --list /tmp/$backupName
if ($LASTEXITCODE -ne 0) { throw 'Archive listing failed' }
& $dockerCli @base cp "postgres:/tmp/$backupName" $backupPath
if ($LASTEXITCODE -ne 0) { throw 'Binary-safe archive copy failed' }
$sourceHashLine = & $dockerCli @base exec -T postgres sha256sum /tmp/$backupName
if ($LASTEXITCODE -ne 0) { throw 'Source checksum failed' }
$sourceHash = ($sourceHashLine -split '\s+')[0]
$localHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
if ($sourceHash.ToUpperInvariant() -ne $localHash) { throw 'Archive checksum mismatch' }
[System.IO.File]::WriteAllText($backupPath + '.sha256', $localHash)
Get-Item -LiteralPath $backupPath | Select-Object Name,Length
```

Never pipe binary dump bytes through PowerShell or use `>` for the dump. Save the
checksum and identity/release metadata with the protected archive. Dumps contain
private prompts/output; existing off-host encryption/retention decisions still
apply. A TOC listing and checksum prove transport integrity, not restorability.

Restore **only into a new disposable drill**, never over either application DB:

```powershell
$restoreProject = "agentflow-v2-backupcheck-$releaseStamp"
$restore = @('--context','desktop-linux','compose','-p',$restoreProject,'-f','deploy/compose.restore.yml')
& $dockerCli @restore config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Drill configuration invalid' }
& $dockerCli @restore up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Drill startup failed' }
$restoreId = & $dockerCli @restore ps -q restorecheck
& $dockerCli --context desktop-linux inspect $restoreId --format '{{.Name}}|{{json .Mounts}}|{{.HostConfig.NetworkMode}}'
# REQUIRE this new project, tmpfs data, no named volumes, no network or ports.
& $dockerCli @restore cp $backupPath restorecheck:/tmp/verify.dump
if ($LASTEXITCODE -ne 0) { throw 'Drill copy failed' }
$restoreHashLine = & $dockerCli @restore exec -T restorecheck sha256sum /tmp/verify.dump
if ($LASTEXITCODE -ne 0) { throw 'Drill checksum failed' }
if ((($restoreHashLine -split '\s+')[0]).ToUpperInvariant() -ne $localHash) { throw 'Drill checksum mismatch' }
& $dockerCli @restore exec -T restorecheck pg_restore -U restorecheck -d restorecheck --exit-on-error --single-transaction --no-owner --no-acl /tmp/verify.dump
if ($LASTEXITCODE -ne 0) { throw 'Drill restore failed' }
& $dockerCli @restore exec -T restorecheck psql -U restorecheck -d restorecheck -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version;' -c 'SELECT count(*) FROM tasks;' -c 'SELECT count(*) FROM agent_executions;' -c 'SELECT count(*) FROM custom_agents;' -c 'SELECT count(*) FROM custom_agent_executions;' -c 'SELECT count(*) FROM custom_workflows;' -c 'SELECT count(*) FROM custom_workflow_runs;' -c 'SELECT count(*) FROM custom_workflow_step_runs;'
if ($LASTEXITCODE -ne 0) { throw 'Drill data verification failed' }
foreach ($table in $contentTables) {
    $digestSql = "SET TIME ZONE 'UTC'; SELECT count(*)::text || ':' || coalesce(md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id)), '') FROM $table t;"
    $digestLines = & $dockerCli @restore exec -T restorecheck psql -U restorecheck -d restorecheck -At -v ON_ERROR_STOP=1 -c $digestSql
    if ($LASTEXITCODE -ne 0) { throw 'Restored content manifest failed' }
    if (($digestLines | Select-Object -Last 1) -ne $sourceManifest[$table]) { throw 'Restored content differs from frozen source' }
}
```

Compare all eight legacy content tables (including `custom_workflow_steps`), counts,
FK consistency and representative histories to the frozen source snapshot. Preserve
the drill for review; stopping its tmpfs server destroys its temporary contents.
Rehearse migration/application reads on a separately network-isolated copy before
accepting the backup. Do not attach the drill to a production app network.

### 4. Apply exactly 0006 and verify

```powershell
& $dockerCli @v2 run --rm --no-deps migrate alembic upgrade 0006_durable_executions
if ($LASTEXITCODE -ne 0) { throw 'Migration failed: keep traffic stopped; never stamp' }
& $dockerCli @v2 run --rm --no-deps migrate python -m app.verify_durable_schema
if ($LASTEXITCODE -ne 0) { throw 'Schema verification failed: keep traffic stopped' }
& $dockerCli @base exec -T postgres psql -U agentflow -d agentflow -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version;' -c 'SELECT count(*) FROM durable_executions;'
if ($LASTEXITCODE -ne 0) { throw 'Revision/journal verification failed' }
```

Require unchanged legacy table counts/digests under the write freeze, no non-null
orphan journal links, and an empty journal on the first 0005 cutover. The verifier
uses a read-only transaction and checks columns/types/nullability, PK/unique/FKs,
checks, expiry index and validated/nondeferrable constraints. It does not repair.
If DDL fails, inspect revision and table state; fixture evidence proves transaction
rollback, but verify the actual failure. Do not assume revision alone proves safety.

### 5. Start only approved application containers and reopen private traffic

```powershell
& $dockerCli @v2 up -d --no-deps --no-build --wait backend frontend
if ($LASTEXITCODE -ne 0) { throw 'V2 app health failed; keep proxy stopped' }
& $dockerCli @v2 exec -T backend python -m app.verify_durable_schema
if ($LASTEXITCODE -ne 0) { throw 'Runtime schema check failed' }
# Verify read-only history/counts inside the maintenance boundary before opening traffic.
& $dockerCli @v2 start proxy
if ($LASTEXITCODE -ne 0) { throw 'Private proxy restart failed' }
.\backend\.venv\Scripts\python.exe deploy/check_private_health.py --mode durable
if ($LASTEXITCODE -ne 0) { throw 'Stop private traffic and investigate' }
```

Confirm loopback-only 8443, explicit trusted CA verification, missing/invalid bearer
rejection, authenticated dashboard/history/status reads, no orphaned running leases,
and UI restoration of existing history. New executions require deliberate user
intent. A paid model smoke is optional and needs **separate explicit authorization**;
the health script performs GETs only. Do not run offline test harnesses against a
production URL or enable fake providers in production.

## B. Recovery and rollback (separate approved maintenance action)

1. Suspend traffic with the selected `$v2` configuration; retain the DB and all
   journal/partial records. Record running journal IDs, expiry/heartbeat timestamps
   and dispatch-intent classifications without dumping prompts, raw keys or tokens.
2. Drain active work. Stop application containers gracefully. Never assume killed
   threads mean a provider call was cancelled or unbilled. No new-key replay of
   uncertain calls. Wait for lease expiry and reconcile journal state while still
   in maintenance; an enabled recovery-only process can call `recover_expired()`
   without invoking providers. This updates only journaled expiries, never legacy
   unleased records. Obtain approval for any production reconciliation writes.
3. Prefer the tested durable-aware backend/frontend with the flag disabled,
   preserving 0006 and tombstones. The current UI prevents ambiguous legacy retry.
   Do not reopen execution traffic with unresolved running jobs. Disabling the
   feature stops startup/periodic recovery; running journal rows are not magically
   resolved by toggling the flag.

```powershell
# Use the recorded reviewed image variables and $disabled argument array above.
& $dockerCli @v2 stop proxy frontend backend
if ($LASTEXITCODE -ne 0) { throw 'Could not enter rollback maintenance' }
# Reconcile/drain before this step. Do not downgrade or drop 0006.
# Within the approved rollback window, only after owners stop and leases expire:
# & $dockerCli @v2 run --rm --no-deps migrate python -c "from app.durable_execution import recover_expired; print(recover_expired())"
# Repeat bounded batches only while expired journal rows remain; never replay calls.
& $dockerCli @disabled up -d --no-deps --no-build --wait backend frontend
if ($LASTEXITCODE -ne 0) { throw 'Disabled-mode app health failed' }
& $dockerCli @disabled start proxy
if ($LASTEXITCODE -ne 0) { throw 'Private proxy restart failed' }
.\backend\.venv\Scripts\python.exe deploy/check_private_health.py --mode disabled
if ($LASTEXITCODE -ne 0) { throw 'Keep execution traffic suspended and investigate' }
```

The schema is additive, so older V1 images can read legacy tables with 0006 present;
however, V1 does not enforce journal keys or fencing. Restoring V1 images requires a
separate maintenance/reconciliation decision and quarantining unresolved durable
work, not simply changing image tags and allowing retries. Never delete journal
records to make an old client succeed.

Diagnose stalls using `state`, `lease_expires_at`, `heartbeat_at`, `completed_at`,
dispatch intent, registered request IDs and authenticated saved history. Check DB
reachability/locks, application recovery-loop health and lease/heartbeat settings.
`SKIP LOCKED` defers locked rows. Re-enable recovery only against the verified schema;
it never resumes paid work. No output/token values can be reconstructed for a call
whose result was never committed.

A backup restore is necessary only for verified corruption or a separately approved
data-recovery decision; application rollback alone does not require it. Freeze
writes, retain the original DB/volume, restore into a **fresh target**, reconcile all
post-backup writes/provider outcomes and lost idempotency reservations, validate,
then deliberately switch connections. Restoring an old snapshot can lose keys and
cause paid duplicates. Never restore over the current DB, use `--clean` there,
delete a volume, or describe restoration as lossless/automatically reversible.

References: [PostgreSQL 16 pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html),
[pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html),
[Compose overlay merging](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/).
