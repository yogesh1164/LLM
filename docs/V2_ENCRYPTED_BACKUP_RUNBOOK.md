# Encrypted PostgreSQL backup and isolated recovery

Status on 2026-10-24: **implemented and tested with synthetic data only**.
No production backup, remote upload, remote storage configuration, credential
change or scheduled job activation occurred. Off-host delivery remains an operator
release gate. The existing database volumes and services are untouched.

## What the tooling does

[`ops/backup/backup.py`](../ops/backup/backup.py) explicitly checks the selected
database name, login role and PostgreSQL major version 16. It checks SELECT
permissions, creates a consistent custom-format `pg_dump`, reads the archive with
`pg_restore --list`, hashes the binary archive, encrypts it with the maintained
[`cryptography.Fernet` recipe](https://cryptography.io/en/latest/fernet/), decrypts
it locally, compares hashes and rechecks archive readability. It publishes only
the authenticated ciphertext and an informational JSON manifest to a filesystem
destination, then checks destination SHA-256. Passwords are never accepted as CLI
arguments, printed or placed in manifests. No shell or PowerShell binary pipeline
is used. PostgreSQL's [custom archive format and consistency guarantees](https://www.postgresql.org/docs/16/app-pgdump.html)
are provided by `pg_dump`.

Fernet provides authenticated encryption using the library's established recipe;
the JSON manifest is not authenticated and is not trusted to authorize recovery.
Ciphertext tampering and wrong keys fail before plaintext is written. Hashes
detect delivery errors; only authenticated decryption establishes ciphertext
integrity. The key holder and destination access controls remain trust boundaries.

The deliberate **256 MiB plaintext archive limit** bounds Fernet memory use.
Memory consumption is several times the archive size. If the real compressed
backup exceeds this limit, this implementation is not approved for that dataset:
select and review a streaming authenticated-encryption adapter (for example age),
run another synthetic and representative-size restore drill, and revise this
limit/design explicitly. It never truncates or downgrades encryption.

## Prerequisites and credential custody

1. Operator approves the exact source endpoint, database, backup login and schedule.
   Use the SELECT-only role from [database role rollout](V2_DATABASE_ROLES.md),
   including future-table/sequence defaults. `pg_dump` fails closed on missing
   privileges or inaccessible RLS-protected rows. Do not grant superuser to solve it.
2. Install PostgreSQL 16 client tools on the backup worker, or explicitly select a
   container with those clients using `--container`. Native libpq uses the current
   worker's `PGPASSFILE`; container mode uses a protected libpq passfile already
   mounted in that container. Do not pass a password through arguments or logs.
   Do not reuse the application's migration or administrator credentials.
3. Install the isolated worker requirements, not an unreviewed application update:

   ```powershell
   py -3.12 -m venv C:\AgentFlowBackupWorker
   C:\AgentFlowBackupWorker\Scripts\python.exe -m pip install -r ops\backup\requirements.txt
   ```

4. Precreate a restricted spool directory on an encrypted worker disk and a
   separate restricted key directory. On Windows use NTFS ACLs granting only the
   backup service identity, necessary recovery custodians and administrators.
   POSIX temp directories are private; Windows directories inherit ACLs, so
   **operator ACL verification is required before any real backup**. Plaintext dump
   files are transient and deleted on success/failure, but this is not secure
   erasure on SSDs. A killed worker may leave a spool directory: treat it as
   sensitive, investigate, and remove it explicitly after recovery.
5. Generate the key once, into the separate restricted directory:

   ```powershell
   C:\AgentFlowBackupWorker\Scripts\python.exe ops\backup\make_key.py C:\AgentFlowKeys\backup-2026-10.fernet-key
   if ($LASTEXITCODE -ne 0) { throw 'Backup key creation failed' }
   ```

   Existing keys are never overwritten. Keep an independently protected copy in an
   operator-controlled secret manager or offline recovery vault. Do not store key
   files beside archives, in Git, in environment files, in task arguments containing
   their contents, or in the off-host archive account. Record key custody and the
   creation date externally. Test recovery custody before relying on the backup.

## Backup and delivery (PowerShell 5.1)

The following is an **operator execution template**, not an action performed in
this engineering run. Replace all endpoint/identity/path examples after approval.
The backup script defaults to fixture database prefixes; a real source also needs
the explicit read authorization flag. The database, user and endpoint are always
required/explicit; the script does not read `.env` or application settings.

```powershell
$backupPython = 'C:\AgentFlowBackupWorker\Scripts\python.exe'
& $backupPython ops\backup\backup.py backup `
  --database '<approved-database>' --user '<approved-backup-role>' `
  --host '<approved-private-db-host>' --port 5432 `
  --key-file C:\AgentFlowKeys\backup-2026-10.fernet-key `
  --spool C:\AgentFlowBackupSpool `
  --destination '\\approved-offhost-server\agentflow-encrypted' `
  --allow-production-read
if ($LASTEXITCODE -ne 0) { throw 'Encrypted backup failed; alert operator' }
```

For a local test adapter replace `--destination` with a local test directory.
No binary data goes through PowerShell stdout/redirection. Python streams
`pg_dump` bytes directly into a binary file and streams archives into `pg_restore`.
The destination must support exclusive file creation and hard-link publication;
unsupported remote filesystems fail rather than weaken overwrite protection.
UUID filenames avoid overwrite; a failed manifest publication can leave an orphan
ciphertext artifact, which must not be treated as a successful backup.
Every PostgreSQL/client subprocess has a default 300-second timeout, configurable
with `--command-timeout-seconds`; `pg_dump` also has a 30-second lock-wait limit.
Timeout failures produce a nonzero sanitized result and clean temporary files.
Set an overall worker/scheduler deadline as well: operating-system filesystem I/O
to an unresponsive mounted destination is outside the PostgreSQL client timeout.
After a container-client timeout inspect for orphaned client operations before a
manual retry; do not restart the database to clear them automatically.

To enable real off-host service: provision an independent private storage host,
restricted dedicated archive identity and encrypted transport (for example a
private SMB3 encrypted share); verify mount/server identity independently; grant
the worker create/read but no broad administration; verify hard-link support;
configure immutability/versioning and capacity alerts; run a synthetic delivery and
re-download/restore from another worker. A local path can also be a mounted remote
filesystem: the script cannot attest its physical location or transport security,
so it always reports `off_host_verified: false`. Record independent remote
attestation with server, account, timestamp and restore evidence. A local success
alone never closes the off-host release gate. Object storage needs a separately
reviewed adapter; no object-account access was invented or configured here.

## Failure detection and retention

Schedule the backup through Windows Task Scheduler using the dedicated service
identity, restricted working directory and a wrapper that throws/exits nonzero on
`$LASTEXITCODE`. Set bounded runtime and prohibit overlapping jobs. Configure an
external heartbeat/Task Scheduler failure alert for nonzero exit **and a missing
execution**. A backup script alone cannot alert if the host never runs it.

Independently schedule the delivered-artifact monitor:

```powershell
& $backupPython ops\backup\monitor.py `
  --destination '\\approved-offhost-server\agentflow-encrypted' --max-age-hours 26
if ($LASTEXITCODE -ne 0) { throw 'Backup missing, stale or damaged; alert operator' }
```

The monitor fails on missing/stale manifests, missing/corrupt ciphertext, invalid
paths and future timestamps. It does not use a decryption key and explicitly does
not attest restoration or off-host location. Set thresholds to the approved RPO.

Proposed policy pending operator acceptance: daily backups retained for 30 days,
one separately retained monthly backup for 12 months, and an immutable retention
window covering the incident-detection horizon. Configure retention with the remote
store's lifecycle mechanism after a successful independent restore; **no automatic
backup deletion is enabled by these scripts**. Keep at least two verified recovery
points and never delete the last known-good set. Monitor capacity and lifecycle
jobs. Logical daily backups imply a potential 24-hour RPO, not point-in-time
recovery; WAL archiving/PITR is not implemented here.

Rotate backup login credentials independently of the encryption key: provision a
replacement least-privilege login, verify backup/restore with it, update the
protected passfile atomically, monitor, then revoke the old login explicitly.
For key rotation generate a new exclusive key file, change the scheduled key path
and external key-to-date inventory, run and restore a new backup, then preserve old
keys until every corresponding backup expires and legal/incident holds clear.
Never rotate by overwriting the sole key. Restrict key recovery to separate
custodians and audit access.

## Isolated restore and disaster recovery

Restore only trusted authenticated archives. PostgreSQL restoration executes
source database SQL; encryption does not make an untrusted source safe.

1. Provision a new private PostgreSQL 16 instance and an empty database named
   `agentflow_restore_<incident-or-drill-id>`. Preserve the source and existing
   volumes. Establish the migration owner role and public-schema restrictions from
   the role runbook; do not restore into a live database.
2. Retrieve ciphertext and its manifest from the independent destination, compare
   SHA-256, and retrieve the correct key through separate custody. The manifest is
   informational; authenticated decryption is mandatory.
3. Use this explicit template. `--execute-restore` is required; the program rejects
   other database prefixes and any target containing application relations,
   functions or custom enum/domain/composite/range types. Restore is transactional, exits on errors, and never uses
   `--clean`, `--create` or DROP operations.

   ```powershell
   & $backupPython ops\backup\backup.py restore `
     --database agentflow_restore_drill --user '<approved-restore-operator>' `
     --host '<isolated-host>' --port 5432 `
     --artifact C:\EncryptedRecovery\agentflow-example.fernet `
     --key-file C:\AgentFlowKeys\backup-2026-10.fernet-key `
     --spool C:\AgentFlowRestoreSpool --restore-owner '<migration-owner>' `
     --execute-restore
   if ($LASTEXITCODE -ne 0) { throw 'Isolated restore failed' }
   ```

4. Original ownership/ACLs are deliberately not replayed. `--restore-owner`
   creates restored objects as the approved migration owner (restore operator must
   be permitted to SET ROLE); omit it only for a disposable drill. Reapply explicit
   runtime/backup grants and owner default privileges from the role runbook.
   Cluster roles, secrets, PostgreSQL configuration, TLS material and encryption
   keys are not included in this single-database archive and need separate custody.
5. Verify `alembic_version` (candidate head `0007_accounts_ownership`), all expected
   tables/constraints/indexes, task/history counts, representative users and
   account sessions, nullable legacy ownership, durable journal ownership and
   recorded outputs. Compare independently retained counts/digests. Check table
   owners and runtime DDL denial. Disable replay of unknown upstream outcomes;
   do not automatically resubmit durable work. Run offline API/browser acceptance.
   Revoke restored sessions/recover credentials under approved incident procedures
   before exposing an old snapshot; a backup can contain previously valid sessions.
6. Record elapsed restore/validation time and accepted data loss. No production
   RTO was established by the small synthetic drill. Switching traffic,
   credentials, ownership or feature flags requires a separate operator decision.

## Reproducible evidence

```powershell
backend\.venv\Scripts\python.exe -m pytest ops\backup -q
backend\.venv\Scripts\python.exe -m ruff check ops\backup
backend\.venv\Scripts\python.exe ops\backup\verify_fixture.py `
  --app-image agentflow-backend:v2-accounts-final-tests `
  --report backups\v2-encrypted-backup-evidence.json
```

Verified on 2026-10-24: **14 offline tests passed**, Ruff passed; a newly named,
network-less tmpfs PostgreSQL **16.15** fixture migrated from empty through
`0007_accounts_ownership`. A non-superuser SELECT-only backup role dumped the
schema and synthetic account/session, owned Unicode task and durable journal
records. Authenticated encrypt/decrypt, archive readability, local delivery and
SHA-256 verification passed. Restoration into a second empty database with a
separate non-login owner produced **15 matching table snapshots** including
migration revision, account/record ownership and journal content; every restored
application table belonged to the requested restore owner. Fixture containers were
removed without deleting volumes; transient synthetic keys/archives were cleaned.
The restored database also passed the application's `verify_account_readiness()`
schema/admin/relationship/idempotency-scope integrity verification.
Tamper, wrong-key, overwrite, identity/version mismatch, existing/nonfixture restore
targets, separate-key storage, size bound, stale/missing/corrupt deliveries and
unsafe manifest paths have automated coverage. Client timeouts and malformed
monitor JSON also have sanitized-failure coverage. The evidence JSON contains
hashes and synthetic identities only. This does **not** demonstrate a real remote backup,
production restoration, scheduler activation or production recovery objectives.
