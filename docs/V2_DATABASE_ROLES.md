# PostgreSQL 16 role rollout and recovery

Status on 2026-10-24: implemented and tested **only in a new disposable instance**.
Existing development/production databases, roles and connection configuration were
not changed. Production application-role replacement remains operator-authorized work.

Latest interruption review: the authorized **read-only catalog capture** found
PostgreSQL 16.15, revision `0005_custom_workflows`, nine application tables owned
by `agentflow`, and that role had SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/
BYPASSRLS enabled. It made no role or ACL changes. The plan remains **not ready to
apply**: six 0007 tables do not yet exist in the observed 0005 snapshot, so the
post-migration grant candidates require approved 0006/0007 migrations and a fresh
catalog capture. See [the dry-run report](V2_DATABASE_ROLE_DRY_RUN.md). No
production credential or connection was changed.

The continuation from checkpoint `2c1e7d1` adds an
[offline production-role dry-run package](V2_DATABASE_ROLE_DRY_RUN.md) with explicit
catalog provenance, commented SQL export and approval sequencing. Production
read-only catalog inspection confirmed the existing application role is overprivileged;
the sanitized findings and before/after-migration plan are in that document. No
production roles, credentials, records, connection configuration or services changed.

## Design

| Role | Permitted work | Excluded rights |
|---|---|---|
| `agentflow_runtime` | CONNECT, public USAGE, explicit application-table SELECT/INSERT/UPDATE/DELETE; users SELECT and UPDATE of password_hash/credential_changed_at; account_audit SELECT/INSERT; ownership_assignments/alembic_version SELECT | Database/schema CREATE, TEMP, table ownership/DDL/TRUNCATE, role management, migration membership, account-role/enabled updates, ownership assignment writes, audit deletion |
| `agentflow_migrator` | CONNECT; owns public schema and application tables; Alembic and approved offline provisioning/recovery | Superuser, CREATEDB, CREATEROLE, replication, BYPASSRLS |
| `agentflow_backup` | CONNECT, schema USAGE, all app-table SELECT and sequence SELECT | Writes, DDL, role membership, broad pg_read_all_data privileges |
| `agentflow_operator` | NOLOGIN, NOINHERIT; explicitly SET ROLE migrator for approved application administration | Superuser, CREATEDB, CREATEROLE, replication, BYPASSRLS |

All four start NOLOGIN; credentials are set separately outside Git/logs. Operators
use individually attributable login roles granted SET membership by the cluster DBA.
Cluster administration and break-glass ownership recovery stay with a separately
protected DBA account; the application operator is not a cluster administrator.

The current schema uses UUID/string keys and has **no sequences**. Runtime gets no
unneeded sequence privileges. A future migration requiring sequences must explicitly
grant `USAGE` on its named sequence to runtime, transfer sequence ownership to the
migrator, and exercise nextval/backup/restore. Backup default SELECT on newly created
tables/sequences is scoped to this creator/schema. Runtime default DML is deliberately
absent: future tables require a reviewed grant. Public function EXECUTE defaults are
revoked for the migrator; no app functions require execution today.

`search_path = public, pg_temp` keeps pg_catalog implicitly first and pg_temp last;
PUBLIC has no public-schema privileges. Runtime lacks CREATE/TEMP and never owns
the database/schema/tables. Audit all other schema CREATE grantees and creator default
ACLs before approval. Ownership isolation remains application enforced: runtime can
read application rows across users through SQL. This design is not RLS, and database
credential compromise is not contained to a single account.

## Read-only preflight and safe ordering

Use backend's Python environment (PowerShell 5.1 compatible). Configure
`AGENTFLOW_OPERATOR_DATABASE_URL` through an operator secret manager/protected
process environment; never copy credentials into a transcript. No environment file
is overwritten by the tooling. A libpq service/passfile may supply connection secrets.

```powershell
backend\.venv\Scripts\python.exe deploy\postgres_roles.py inventory
backend\.venv\Scripts\python.exe deploy\postgres_roles.py bootstrap --expected-database agentflow
```

The first command only reads catalogs. The second prints proposed SQL and makes no
changes. Inspect actual database/server address, version, owner, memberships, public
schema ACL, default ACLs and all table owners. Additionally inventory existing role
grants, sequences, functions, extensions and dependents with psql `\du+`, `\dn+`,
`\dp public.*`, `\ddp`, `\df+ public.*`. Never print `pg_authid` password hashes.
Confirm the connection's actual server endpoint against the approved deployment.

1. Approve an outage/cutover plan, obtain a verified encrypted backup, and test
   recovery. Verify this database is dedicated to AgentFlow: revoking PUBLIC CONNECT
   or TEMP can affect other clients. Inventory the old application role's ownership,
   superuser flags, memberships and cross-database use; do not assume its name.
2. Review bootstrap SQL. Existing target role names cause transactional failure;
   reconcile them manually rather than silently inheriting potentially unsafe rights.
3. The DBA runs the reviewed phase with **explicit** `--apply`. Bootstrap changes
   role/schema/database privileges in one transaction; it is not run automatically.
4. For existing installations, transfer only the inventoried application tables to
   migrator using the reviewed grants phase before migrations. Never use broad
   `REASSIGN OWNED` without a reviewed cluster-wide dependency inventory.
5. Assign distinct credentials using a secure DBA psql session: `ALTER ROLE
   agentflow_migrator LOGIN;` then `\password agentflow_migrator`; repeat for runtime
   and backup. Use SCRAM and TLS/verified server identity for remote connections.
   Keep migration/operator credentials out of runtime containers.
6. Run Alembic under migration credentials, sequentially inspecting 0005, 0006 and
   0007. Use the existing `DATABASE_URL` process configuration for the one-shot
   migrator; never point the application process at these credentials.
7. Review/apply current grants after migrations (and after every future migration):

```powershell
backend\.venv\Scripts\python.exe deploy\postgres_roles.py grants --expected-database agentflow
# Only after operator approval of the printed statements:
backend\.venv\Scripts\python.exe deploy\postgres_roles.py grants --expected-database agentflow --apply
```

The grant phase rejects unknown public tables and atomically transfers each reviewed
table, revokes PUBLIC/runtime/backup table ACLs **and independent column ACLs**,
then grants the precise list above. Column ACLs are included in read-only inventory;
the reviewed SQL enumerates live columns through PostgreSQL catalogs with safely
quoted identifiers. Table-level REVOKE alone would leave old column grants active.
Public schema transfer during bootstrap is intentional. Retain database ownership
with the DBA; runtime must never own it. On an existing database review and remove
old owner-specific/default grants, schema CREATE grants and old role memberships
explicitly. Do not revoke shared-role privileges blindly.

8. Verify using a fresh runtime login (not a session that previously SET ROLE).
   Read `alembic_version`, exercise account login/logout/password change, all resource
   boundaries, duplicate submission and heartbeat/recovery. Test denied DDL in a
   transaction against a disposable clone; production privilege inspection is read-only.
9. Configure backend `DATABASE_URL` with runtime credentials in the approved secret
   store, enable the separately reviewed Compose role overlay, and perform the
   controlled application restart only in the approved maintenance window.
10. Disable the old application login after reviewing shared use and terminating
    only explicitly approved old sessions. Remove obsolete superuser/role/schema
    privileges as an independently reviewed DBA action. Retain recovery access.

Useful verification SQL (runtime connection):

```sql
SELECT current_database(), current_user, current_setting('search_path');
SELECT version_num FROM public.alembic_version;
SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname=current_user;
SELECT has_database_privilege(current_user,current_database(),'CREATE') AS create_db_objects,
       has_database_privilege(current_user,current_database(),'TEMP') AS temporary_objects,
       has_schema_privilege(current_user,'public','CREATE') AS create_public;
SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public';
SELECT pg_has_role(current_user,'agentflow_migrator','MEMBER');
SELECT has_table_privilege(current_user,'public.tasks','TRUNCATE');
SELECT has_column_privilege(current_user,'public.users','role','UPDATE');
```

Expect all listed role/privilege booleans false; tables owned by migrator. Retain an
operator-readable ACL inventory with the release evidence. Runtime may UPDATE only
the two credential columns on users; bootstrap/account recovery/legacy assignment
must use approved offline migrator/operator execution.

## Rotation, rollback and recovery

Rotate runtime/backup/migration independently. Create an individually scoped new
login with the same reviewed memberships or securely change its password; update
only the approved secret reference; test a new connection; reload/restart the affected
service during its approved window; revoke/disable the former credential and review
old sessions. PostgreSQL password changes do not invalidate existing connections.
Never grant runtime membership in migrator as a workaround for failed queries.

If runtime acceptance fails, halt activation, capture redacted errors and repair
only the missing named privilege after review. An application rollback can retain
the additive 0007 schema and least-privilege roles if the selected older build was
tested against them. Do not downgrade 0006/0007 or restore over a live database.
DBA recovery can temporarily restore the previous **reviewed** connection secret
and ACL inventory during an approved window; this revives the former privilege risk
and requires explicit acceptance. For data recovery restore encrypted backup into a
new isolated database, recreate roles and reapply ACLs, verify contents/owners, and
switch connections only after operator approval. pg_dump does not back up global
roles/passwords: retain this role design and secret-store recovery separately.

## Reproducible isolated evidence

On 2026-10-24 a new `agentflow-v2-leastpriv-20261024-db`, PostgreSQL **16.15**, used
`--network none`, tmpfs PGDATA, no ports/volumes. The test runner shared only that
container's network namespace. `tests/test_postgres_least_privilege.py`: **2 passed**.
It ran actual SQLAlchemy migrations 0005→0006→0007 and repeat head; provisioned two
synthetic accounts under migrator; used runtime for authenticated mocked workflows,
cross-user/admin denial, duplicates, journal/heartbeat/stage persistence, login,
password change and revoked-session checks. Fourteen forbidden statements failed,
including schema/table/TEMP/role DDL, migration SET ROLE, TRUNCATE, role/enabled
updates, audit deletion, migration writes and ownership-manifest insertion.
Backup could SELECT every table and future tables/sequences by default; runtime
could not access a newly created unreviewed table.

`pg_dump -Fc` authenticated as backup succeeded; `pg_restore --list` read the archive
(115 TOC entries). Restore as migrator into a second new isolated database succeeded
with `--exit-on-error`; revision 0007, 2 users, 1 task and 3 journal records survived;
all 15 public tables were owned by migrator. No production data was read or backed up.
The run's Ruff checks passed. A second new isolated instance
`agentflow-v2-colacl-20261024-db` verified the hardened final role tooling: **4 passed**,
including two added CLI tests (secret-bearing connection errors are redacted and
real SQLAlchemy transaction failure rolls back). The integration deliberately seeded
UPDATE(role, enabled) column grants to PUBLIC, runtime and backup; applying the
reviewed grant phase removed them, and both runtime and backup update attempts
were denied while normal runtime authentication continued to work. CLI failures
emit a fixed redacted diagnostic and nonzero status; inspect catalogs privately
before retrying after a connection/commit interruption, since commit outcome may
be unknown. No raw SQLAlchemy exception, connection URL or parameters are printed.
This proves the isolated role design, not production
credential rotation, existing-role cleanup or production readiness.

Primary references: [PostgreSQL privileges](https://www.postgresql.org/docs/16/ddl-priv.html),
[schema/search-path security](https://www.postgresql.org/docs/16/ddl-schemas.html),
[consistent custom-format backups](https://www.postgresql.org/docs/16/app-pgdump.html).
