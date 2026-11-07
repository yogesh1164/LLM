# Production database role change: offline review package

## 2026-10-25 review gate

This remains an **offline proposal**, not an authorized production change.
The last read-only production catalog audit showed the shared `agentflow` role
with SUPERUSER, CREATEDB, CREATEROLE, REPLICATION and BYPASSRLS, and Alembic
revision 0005. The `ready_to_apply` decision is false. Prior PostgreSQL 16
disposable-fixture tests covered 0005 → 0006 → 0007, runtime authentication,
ownership/session/journal/heartbeat operations, 14 forbidden administrative or
schema operations, backup SELECT permissions and rollback/error handling.
This continuation could not repeat containerized PostgreSQL tests because the
local Docker daemon was unavailable. Hosted CI for source `0aab361` passed the
least-privilege and durable PostgreSQL jobs; it does not test production state.

Before execution, require an operator-approved encrypted recovery point and
restore drill, exact database/role/revision re-audit, maintenance window,
credential custody, separate runtime/migration/backup/operator connection
strings, and explicit approvals for creating roles, rotating credentials,
applying 0006/0007, changing grants, switching application connections and
activating accounts/durable execution. Rehearse both the grant-change and
connection-string rollback against disposable PostgreSQL 16 with the actual
candidate images. Schema and ownership-audit migrations are not safely
reversible by simply restoring old grants; a data-preserving rollback or isolated
restore and traffic-switch plan needs separate review. No existing database,
role, password, grant or connection string was changed in this continuation.

## Current status — 2026-10-24

The saved run is a read-only catalog observation, not a role rollout. It records
PostgreSQL 16.15 at `0005_custom_workflows`, nine current tables, and the
overprivileged `agentflow` role. The generated 18-statement bootstrap, 45-statement
pre-migration phase and 77 separately labelled post-migration candidates are
comment-only SQL. `ready_to_apply=false`; no credentials, grants, migration or
runtime connection changed. Latest isolated full suites passed (Linux 407/2
skipped/1 xfailed; Windows 373/36 skipped/1 xfailed); operator-specific target
inventory and approvals remain necessary.

This continuation prepared a production-role change using an **authorized read-only
production catalog inspection** and offline planning. The existing application role
was confirmed overprivileged. No production passwords, grants, ownership, migrations,
application records, connection strings or services were changed.

The role architecture and verified rollback guidance are in
[V2_DATABASE_ROLES.md](V2_DATABASE_ROLES.md). This document describes the new offline
planning step; it does not authorize role changes or cutover.

## Operator-supplied inventory

An authorized operator can collect catalog metadata using the existing connection
selected privately through `AGENTFLOW_OPERATOR_DATABASE_URL`. The inventory phase
now enforces a read-only transaction and a 10-second statement timeout. It exports
UTF-8 itself so PowerShell 5.1 does not change the JSON encoding. Files must not
already exist; no environment file is read or overwritten automatically.

```powershell
# ONLY after the operator separately authorizes the actual target inspection:
backend\.venv\Scripts\python.exe deploy\postgres_roles.py inventory --inventory-output C:\operator-private\role-inventory.json
```

The output includes actual database/server identity and owner, database ACL, all
nonbuiltin roles and privilege flags, noncatalog schema owners/ACLs, memberships
including INHERIT/SET/ADMIN, creator/schema default ACLs, public application table
owners, independent column ACLs, relation owners/ACLs across application schemas,
functions/security-definer flags and installed extensions. It does not query password
hashes, environment files or application content. Treat catalog snapshots as private
operator evidence. Their names and ACLs can describe infrastructure.

Separately verify the current Alembic revision through the existing read-only
`deploy/release_preflight.py` with explicit database/user identity. This catalog
snapshot does not assert the production migration revision. Independently confirm
the database endpoint, backup readiness and inherited privileges, including all
uses of the old application login across databases.

The offline planner has no database connection path:

```powershell
backend\.venv\Scripts\python.exe deploy\postgres_roles.py plan --inventory-file C:\operator-private\role-inventory.json --inventory-provenance operator-supplied --expected-database agentflow --output-directory C:\operator-private\role-review-unique
```

It requires explicit provenance and a matching PostgreSQL 16 database identity.
`--apply` is rejected in plan mode. For an explicitly authorized production catalog
capture, provenance `production-read-only-catalogs` records that actual catalog
metadata was observed; it does not imply production privileges have been changed or
the release is approved. A new output directory receives:

| File | Purpose |
|---|---|
| `role-dry-run.json` | Input SHA-256, preserved catalog evidence, proposed SQL, unknown objects, role-name conflicts, dangerous role flags, required review and approval sequence |
| `role-plan.sql` | Proposed statements with **every line commented out**, preventing accidental execution of an exported plan |

Both report and CLI explicitly state `production_verified: false`,
`database_connection_attempted: false`, `database_changes_performed: false` and
`ready_to_apply: false` (the CLI emits the relevant summary fields). Operator-supplied
inventory remains evidence requiring independent endpoint/freshness confirmation;
it does not convert into an approval. The JSON parser rejects unexpected catalog
row fields, preventing accidental export of password fields. Existing output
directories are rejected rather than overwritten.

## Statements and decisions for review

The proposed bootstrap creates four NOLOGIN/NOINHERIT roles without superuser,
CREATEDB, CREATEROLE, replication or BYPASSRLS; revokes PUBLIC database privileges;
transfers the public schema to migrator; grants CONNECT/USAGE and explicit operator
SET membership; configures creator-scoped default privileges and search paths.
It does not reconcile an existing role with one of these names automatically.

The grants phase transfers only known application tables, removes PUBLIC/runtime/
backup table **and column** privileges, then grants the exact permissions documented
in the role runbook. Unknown public tables withhold the grant plan. Unknown views,
sequences, foreign tables, other schemas and functions are flagged for separate
disposition. Defaults from other creators, privileges granted to unrelated roles,
role memberships and old login/superuser rights are inventoried but not silently
removed. The operator must assess shared use before approving exact revokes.

No script silently retires the old application login, terminates sessions, creates
passwords, switches connections, migrates production, assigns content ownership,
restarts services or activates authentication/durable execution.

## Observed production catalog findings and staged plan

The authorized capture used `BEGIN READ ONLY`, a 10-second statement timeout,
`search_path = pg_catalog, pg_temp`, a single catalog JSON query and `ROLLBACK`.
Only metadata was captured. It confirmed PostgreSQL 16.15 and **9 application tables**;
the separate authorized read-only revision check reported `0005_custom_workflows`.
All nine tables are owned by the existing application role, whose SUPERUSER,
CREATEDB, CREATEROLE, REPLICATION and BYPASSRLS flags are enabled. This confirms
the production least-privilege blocker rather than resolving it.

The public schema is owned by `pg_database_owner`. The capture found no conflicting
target role names, unrecognized application tables/relations, application functions,
creator default ACL entries or independent column ACL entries. Three memberships
were retained for review. These observations do not authorize removing shared-role
rights. Retain a separately verified DBA recovery identity before retiring any
existing administrator credential.

The raw metadata and complete review package are retained locally under ignored
`backups/v2-four-production-role-inventory.json` and
`backups/v2-four-production-role-review/`. Their inventory SHA-256 is
`f3e46249fcc406fc80c204bd2a4b34e2839fa5d9da7179ea1fe96f77a9de8e3c`.
Private server metadata and full ACL dumps are not committed.

The generated review package contains **18 bootstrap statements**, **45 grant/
transfer statements for the observed pre-migration schema**, and **77 separately
labelled post-migration grant candidates**. Every line in the SQL export is
commented. In JSON, `planned_sql.grants` applies only to the nine observed tables.
The separate `post_migration_grants_candidate` phase references the expected 15-table
0007 schema and must not run against the current 0005 database.

Six tables are absent from the current snapshot: `durable_executions`, `users`,
`account_sessions`, `account_audit`, `login_buckets` and `ownership_assignments`.
After separately approved migrations 0006/0007 under the migration role, capture a
fresh complete inventory and generate/review the final grant plan. Reconcile actual
objects with the expected schema before enabling a new runtime connection. No
migration or post-migration privilege change was performed during this dry-run.

Reproduction from the retained capture performs no database connection:

```powershell
backend\.venv\Scripts\python.exe deploy\postgres_roles.py plan --inventory-file backups\v2-four-production-role-inventory.json --inventory-provenance production-read-only-catalogs --expected-database agentflow --output-directory backups\production-role-review-new
```

Approval order:

1. DBA verifies a fresh complete inventory, actual endpoint and current revision.
2. Review unknown objects, dependencies and inherited/shared role use; approve each
   scoped ownership transfer and revoke, including database-wide PUBLIC changes.
3. Accept encrypted backup/key custody/recovery evidence and a maintenance window.
4. Approve role creation and privately provision distinct migration/runtime/backup
   credentials. Keep migration credentials out of runtime containers.
5. Approve migration-role execution of required revisions and final explicit grants.
6. Run runtime authentication, ownership, journal/heartbeat and denied-DDL checks on
   the disposable clone; inspect production privileges read-only.
7. Approve the runtime connection switch and controlled application restart.
8. Approve old credential/session retirement, rollback conditions and final health
   acceptance. Password changes alone do not close existing sessions.

Use the original `bootstrap`/`grants` dry-run followed by separately approved
`--apply` execution described in the runbook. The exported commented SQL is a
review artifact, not an executable deployment path.

## Actual evidence from this continuation

The tracked [synthetic inventory](examples/v2-role-inventory.synthetic.json) uses
documentation-only address `192.0.2.10`, database `agentflow_production_example`,
and synthetic role `legacy_app_example`; its elevated flags demonstrate detection.
It contains no production metadata, credentials or records.

```powershell
backend\.venv\Scripts\python.exe deploy\postgres_roles.py plan --inventory-file docs\examples\v2-role-inventory.synthetic.json --inventory-provenance synthetic --expected-database agentflow_production_example --output-directory backups\operator-role-review-unique
```

The synthetic export succeeded locally; the report retained explicit production
unknowns and required approvals. It remains a separate example from the actual
read-only production metadata report above. A **new**
`agentflow-v2-roleplan-ro-20261024-db` instance used
PostgreSQL 16, tmpfs storage, no network and no published ports/volumes. The role
suite reported **7 passed**. Its new assertions verified the expanded real PostgreSQL
catalog query and offline report against migrated synthetic schema, including
all inventory fields and detection of existing target roles. The final integration
also exported UTF-8 inventory through the CLI and deliberately injected a DELETE
query, verifying PostgreSQL rejected it inside the enforced read-only transaction
and preserved every task. Existing coverage
continued to exercise migrations 0005→0006→0007, runtime API/account ownership,
sessions/password changes, durable journal/heartbeat and forbidden operations.
The prior checkpoint's backup-role dump/migrator restore evidence is reused rather
than presented as a new backup execution here.

Host focused result: **6 passed, 1 intentional PostgreSQL skip**. Added regressions
prove plan mode never creates a database engine, refuses `--apply`, never overwrites
a package, emits only commented SQL, flags unknown/incomplete/conflicting inventory,
rejects extra secret fields, and requires matching identity/version/provenance.

Remaining production blocker: the observed overprivileged runtime role must be
replaced during a separately approved role/credential/migration/maintenance cutover.
Reconfirm inventory freshness and effective/shared grants before approval. No
production least-privilege clearance is claimed.
