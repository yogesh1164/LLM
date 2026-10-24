# Encrypted PostgreSQL backup and isolated recovery

Status on 2026-10-24: **implemented and tested with synthetic data only**.
No production backup, remote upload, remote storage configuration, credential
change or scheduled job activation occurred. Off-host delivery remains an operator
release gate. The existing database volumes and services are untouched.

Latest isolated evidence: `age v1.3.2` encrypted/decrypted a random **300 MiB**
archive with matching SHA-256, and a separately retrieved local destination copy
also matched. Aggregate worker/age peak sampled RSS was 43,765,760 bytes. A
synthetic PostgreSQL 16.15 custom-format archive restored independently and
matched **15 tables** at `0007_accounts_ownership`; restore owner/account readiness
checks passed. Evidence records `off_host_verified: false`: the destination was a
temporary local filesystem, no external provider/account or production schedule was
configured, and no real production artifact was sent. This drill does not set a
production RPO/RTO or prove key-custody recovery.

## What the tooling does

[`ops/backup/backup.py`](../ops/backup/backup.py) explicitly checks the selected
database name, login role and PostgreSQL major version 16. It checks SELECT
permissions, creates a consistent custom-format `pg_dump`, reads the archive with
`pg_restore --list`, hashes the binary archive, encrypts it with the maintained
[age CLI](https://github.com/FiloSottile/age), decrypts
it locally, compares hashes and rechecks archive readability. It publishes only
the authenticated ciphertext and an informational JSON manifest to a filesystem
destination, then checks destination SHA-256. Passwords are never accepted as CLI
arguments, printed or placed in manifests. No shell or PowerShell binary pipeline
is used. PostgreSQL's [custom archive format and consistency guarantees](https://www.postgresql.org/docs/16/app-pgdump.html)
are provided by `pg_dump`.

Age provides authenticated streaming encryption using its [published format](https://age-encryption.org/v1);
the JSON manifest is not authenticated and is not trusted to authorize recovery.
Ciphertext tampering and wrong keys fail before plaintext is published for use.
Age may write authenticated prefix chunks into a private temporary file before a
later chunk fails: that file is removed on any failure and never passed to restore. Hashes
detect delivery errors; only authenticated decryption establishes ciphertext
integrity. The key holder and destination access controls remain trust boundaries.

New CLI backups always use **age X25519 identities and streaming authenticated
encryption**, with no application archive-size cap. Python streams subprocess
output and file copies; age owns encryption, chunk framing and authentication.
No custom cryptographic protocol was implemented. Disk capacity and approved
runtime remain practical bounds: provision protected spool capacity for a dump,
ciphertext, verification plaintext and recovery copies, rather than relying on
RAM proportional to archive size.

Existing `.fernet` archives remain readable by format detection with their original
Fernet key. Their **256 MiB plaintext bound remains intentionally enforced** because
that legacy library recipe buffers whole messages. Do not rename archives or
replace old keys. The Python `backup()` API defaults to identity-based automatic
format selection only to preserve the already verified Fernet rehearsal callers;
new production automation must use the CLI (age-only) or pass `encryption="age"`
explicitly. There is no silent fallback after an age authentication failure.

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
3. Install PostgreSQL clients and age/age-keygen **1.2.1 or later** through an
   operator-trusted distribution/package source; the Windows verification below
   used official **age 1.3.2**. For Windows the upstream recommends
   `winget install --id FiloSottile.age`; Debian workers can use `apt install age`.
   Package installation is a worker prerequisite, not a production-container change.
   Set `--age-binary` / `--age-keygen` to explicit trusted paths if not on PATH.
   Install the isolated worker Python requirements, not an application update:

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
   C:\AgentFlowBackupWorker\Scripts\python.exe ops\backup\make_key.py C:\AgentFlowKeys\backup-2026-10.age-identity --format age
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
  --key-file C:\AgentFlowKeys\backup-2026-10.age-identity `
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
store's lifecycle mechanism after a successful independent restore; **no scheduled
backup deletion is activated**. `retention.py --destination <path>` is a read-only
plan by default: it protects at least the newest two sets and the newest set in
each of the latest 12 represented months, then proposes older-than-30-day pairs.
It validates exact artifact/manifest pairing and ciphertext hashes, refuses
symlinks, and leaves unrelated files untouched. An operator may run deletion only
after reviewing recovery evidence/legal holds, supplying `--execute-local-prune`,
the exact same resolved `--confirm-destination`, and
`--confirm-action DELETE_EXPIRED_ENCRYPTED_BACKUPS`. Do not schedule deletion until
the remote lifecycle/immutability/hold policy has been accepted. Keep at least two verified recovery
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
     --artifact C:\EncryptedRecovery\agentflow-example.age `
     --key-file C:\AgentFlowKeys\backup-2026-10.age-identity `
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
  --report backups\v2-streaming-postgres-backup-evidence.json
backend\.venv\Scripts\python.exe -m pip install -r ops\backup\requirements-test.txt
backend\.venv\Scripts\python.exe ops\backup\verify_large_archive.py `
  --report backups\v2-streaming-backup-memory.json
```

For actual age unit tests set `AGENTFLOW_TEST_AGE_BINARY` and
`AGENTFLOW_TEST_AGE_KEYGEN` to the trusted executables; without them six external
age cases are explicitly skipped, not treated as verified. The large-file harness
uses psutil only for measurement and records aggregate RSS of the separate Python
worker **plus its age subprocesses**, with a requested 10 ms polling delay
(process inspection adds overhead; actual sample counts are recorded).

Verified on 2026-10-24: **26 offline tests passed with age configured**, Ruff passed; a newly named,
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
That PostgreSQL drill read the separately delivered archive into another recovery
directory before decryption; its source spool was not used for restore. Synthetic
backup work took 29.297 s and restore plus validation took 13.172 s; these small
fixture timings exclude operator provisioning/incident response and do not define
a production RTO.
Tamper, wrong-key, overwrite, identity/version mismatch, existing/nonfixture restore
targets, separate-key storage, size bound, stale/missing/corrupt deliveries and
unsafe manifest paths have automated coverage. Client timeouts and malformed
monitor JSON also have sanitized-failure coverage. The evidence JSON contains
hashes and synthetic identities only. This does **not** demonstrate a real remote backup,
production restoration, scheduler activation or production recovery objectives.

Independent synthetic large-file verification used **16 MiB and 300 MiB** random
archives. Both encrypted, copied to a separately named destination, retrieved into
an independent recovery directory, decrypted and matched SHA-256. Measured peak
aggregate Python-worker/age RSS was **43,225,088 bytes** for 16 MiB and
**43,765,760 bytes** for 300 MiB, under the harness's 128 MiB budget. Measured
operation times were 0.781 s and 14.640 s. These are observed Windows measurements,
not production throughput guarantees; 10 ms sampling is not a proof that every
instantaneous allocation was observed. Age's streaming design is the basis for
bounded memory, supported by this scaling check. No real data was used.

The tested Windows age archive SHA-256 was
`f48d8f8f9ebe903ab5027ed067652f2cc1db94bc206976430133b905dcd8e8c7`, matching the
official GitHub v1.3.2 release asset's published digest over HTTPS. No third-party
binary mirrors were used. Independent [Sigsum proof verification](https://github.com/FiloSottile/age/blob/main/SIGSUM.md)
was not performed in this run; use trusted OS packaging or the upstream verification
procedure for the selected worker's toolchain. Downloaded tools, synthetic keys
and archive data are not committed.
