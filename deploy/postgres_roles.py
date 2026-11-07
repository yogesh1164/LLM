"""Reviewable PostgreSQL 16 role SQL. Default action is read-only inventory.

Run with backend's Python environment. No passwords are accepted or printed.
Use a libpq service / protected passfile via AGENTFLOW_OPERATOR_DATABASE_URL.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

ROLES = ("agentflow_migrator", "agentflow_runtime", "agentflow_backup", "agentflow_operator")
APP_TABLES = (
    "tasks", "agent_executions", "custom_agents", "custom_agent_executions",
    "custom_workflows", "custom_workflow_steps", "custom_workflow_runs",
    "custom_workflow_step_runs", "durable_executions", "account_sessions", "login_buckets",
)


def identifier(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("Use a lowercase PostgreSQL identifier")
    return '"' + value + '"'


def bootstrap_sql(database):
    target = identifier(database)
    statements = [
        f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOREPLICATION NOBYPASSRLS NOINHERIT" for role in ROLES
    ]
    statements += [
        f"REVOKE ALL ON DATABASE {target} FROM PUBLIC",
        f"GRANT CONNECT ON DATABASE {target} TO " + ", ".join(ROLES),
        "REVOKE ALL ON SCHEMA public FROM PUBLIC",
        "ALTER SCHEMA public OWNER TO agentflow_migrator",
        "GRANT USAGE ON SCHEMA public TO agentflow_runtime, agentflow_backup",
        "GRANT agentflow_migrator TO agentflow_operator WITH INHERIT FALSE, SET TRUE",
        # Never grant future runtime DML implicitly. New tables require reviewed grants.
        ("ALTER DEFAULT PRIVILEGES FOR ROLE agentflow_migrator IN SCHEMA public "
         "REVOKE ALL ON TABLES FROM PUBLIC"),
        ("ALTER DEFAULT PRIVILEGES FOR ROLE agentflow_migrator IN SCHEMA public "
         "GRANT SELECT ON TABLES TO agentflow_backup"),
        ("ALTER DEFAULT PRIVILEGES FOR ROLE agentflow_migrator IN SCHEMA public "
         "GRANT SELECT ON SEQUENCES TO agentflow_backup"),
        ("ALTER DEFAULT PRIVILEGES FOR ROLE agentflow_migrator IN SCHEMA public "
         "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"),
    ]
    for role in ROLES:
        statements.append(f"ALTER ROLE {role} IN DATABASE {target} SET search_path = public, pg_temp")
    return statements


def grants_sql(tables):
    """Explicit reviewed current schema; fail closed on unexpected application tables."""
    known = set(APP_TABLES) | {"users", "account_audit", "ownership_assignments", "alembic_version"}
    unexpected = set(tables) - known
    if unexpected:
        raise ValueError("Unreviewed public tables: " + ", ".join(sorted(unexpected)))
    statements = []
    for table in sorted(tables):
        table = identifier(table)
        statements += [f"ALTER TABLE public.{table} OWNER TO agentflow_migrator",
                       f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, agentflow_runtime, agentflow_backup",
                       # Table REVOKE does not remove independently granted column ACLs.
                       f"""DO $acl$ DECLARE column_name text; BEGIN
                       FOR column_name IN SELECT attname FROM pg_attribute
                         WHERE attrelid = 'public.{table}'::regclass
                           AND attnum > 0 AND NOT attisdropped
                       LOOP EXECUTE format('REVOKE ALL (%I) ON TABLE public.{table}
                         FROM PUBLIC, agentflow_runtime, agentflow_backup', column_name);
                       END LOOP; END $acl$""",
                       f"GRANT SELECT ON TABLE public.{table} TO agentflow_backup"]
    for table in APP_TABLES:
        if table in tables:
            statements.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{identifier(table)} "
                              "TO agentflow_runtime")
    for table in ("users", "account_audit", "ownership_assignments", "alembic_version"):
        if table in tables:
            statements.append(f"GRANT SELECT ON public.{identifier(table)} TO agentflow_runtime")
    if "users" in tables:
        statements.append("GRANT UPDATE (password_hash, credential_changed_at) ON public.users "
                          "TO agentflow_runtime")
    if "account_audit" in tables:
        statements.append("GRANT INSERT ON public.account_audit TO agentflow_runtime")
    # Current UUID/string primary keys need no sequences. Future sequences need review.
    return statements


INVENTORY = """
SELECT current_database() AS database, current_user AS connected_role,
       current_setting('server_version_num') AS server_version,
       inet_server_addr()::text AS server_address,
       (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) AS database_owner,
       (SELECT datacl::text FROM pg_database WHERE datname=current_database()) AS database_acl,
       (SELECT json_agg(s) FROM (SELECT nspname, pg_get_userbyid(nspowner) AS owner,
          nspacl::text AS acl FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema') s) AS schemas,
       (SELECT json_agg(m) FROM (SELECT pg_get_userbyid(roleid) AS role,
          pg_get_userbyid(member) AS member, admin_option, inherit_option, set_option
          FROM pg_auth_members) m) AS memberships,
       (SELECT json_agg(a) FROM (SELECT pg_get_userbyid(defaclrole) AS creator,
          n.nspname AS schema, defaclobjtype, defaclacl::text AS acl FROM pg_default_acl d
          LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace) a) AS defaults,
       (SELECT json_agg(r) FROM (SELECT rolname, rolsuper, rolcreatedb, rolcreaterole,
          rolreplication, rolbypassrls, rolcanlogin FROM pg_roles
          WHERE rolname !~ '^pg_') r) AS roles,
       (SELECT json_agg(t) FROM (SELECT tablename, tableowner FROM pg_tables
          WHERE schemaname = 'public') t) AS tables,
       (SELECT json_agg(a) FROM (SELECT c.relname AS table_name, a.attname AS column_name,
          a.attacl::text AS acl FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
          AND a.attnum > 0 AND NOT a.attisdropped AND a.attacl IS NOT NULL) a) AS column_acls,
       (SELECT json_agg(o) FROM (SELECT n.nspname AS schema, c.relname AS name,
          c.relkind AS kind, pg_get_userbyid(c.relowner) AS owner, c.relacl::text AS acl
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
          AND c.relkind IN ('r','p','v','m','S','f')) o) AS objects,
       (SELECT json_agg(f) FROM (SELECT n.nspname AS schema, p.proname AS name,
          pg_get_userbyid(p.proowner) AS owner, p.prosecdef AS security_definer,
          p.proacl::text AS acl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') f) AS functions,
       (SELECT json_agg(e) FROM (SELECT extname AS name, extversion AS version
          FROM pg_extension) e) AS extensions
"""

INVENTORY_LISTS = ("schemas", "memberships", "defaults", "roles", "tables", "column_acls",
                   "objects", "functions", "extensions")
CATALOG_FIELDS = {
    "schemas": {"nspname", "owner", "acl"},
    "memberships": {"role", "member", "admin_option", "inherit_option", "set_option"},
    "defaults": {"creator", "schema", "defaclobjtype", "acl"},
    "roles": {"rolname", "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls", "rolcanlogin"},
    "tables": {"tablename", "tableowner"},
    "column_acls": {"table_name", "column_name", "acl"},
    "objects": {"schema", "name", "kind", "owner", "acl"},
    "functions": {"schema", "name", "owner", "security_definer", "acl"},
    "extensions": {"name", "version"},
}


def dry_run_report(inventory, provenance, expected_database):
    """Prepare a review package offline; catalog input is evidence, never approval."""
    if provenance not in {"synthetic", "operator-supplied", "production-read-only-catalogs"}:
        raise ValueError("Explicit inventory provenance required")
    for field in ("database", "connected_role", "server_address", "database_owner", "database_acl"):
        if field in inventory and inventory[field] is not None and not isinstance(inventory[field], str):
            raise ValueError("Invalid inventory identity field")
    if inventory.get("database") != expected_database:
        raise ValueError("Expected database does not match inventory")
    identifier(expected_database)
    if not 160000 <= int(inventory.get("server_version", 0)) < 170000:
        raise ValueError("PostgreSQL 16 inventory required")
    for field in INVENTORY_LISTS:
        if field in inventory and inventory[field] is not None and not isinstance(inventory[field], list):
            raise ValueError("Invalid inventory list")
        for row in inventory.get(field) or []:
            if not isinstance(row, dict) or set(row) - CATALOG_FIELDS[field]:
                raise ValueError("Inventory must contain only the documented catalog fields")
            if any(value is not None and not isinstance(value, (str, bool)) for value in row.values()):
                raise ValueError("Invalid catalog field value")
    missing = [field for field in INVENTORY_LISTS if field not in inventory]
    for field in ("connected_role", "server_address", "database_owner", "database_acl"):
        if field not in inventory:
            missing.append(field)
    known = set(APP_TABLES) | {"users", "account_audit", "ownership_assignments", "alembic_version"}
    tables = [row["tablename"] for row in (inventory.get("tables") or [])]
    unknown_tables = sorted(set(tables) - known)
    unknown_objects = [obj for obj in (inventory.get("objects") or [])
                       if obj.get("schema") != "public" or obj.get("kind") != "r"
                       or obj.get("name") not in known]
    existing_roles = [row["rolname"] for row in (inventory.get("roles") or [])
                      if row.get("rolname") in ROLES]
    privileged_roles = [row["rolname"] for row in (inventory.get("roles") or [])
                        if any(row.get(key) for key in
                               ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls"))]
    # Keep evidence from the known catalog shape; do not echo arbitrary input fields.
    snapshot = {key: inventory[key] for key in
                (*INVENTORY_LISTS, "database", "connected_role", "server_version", "server_address",
                 "database_owner", "database_acl") if key in inventory}
    blockers = []
    if missing:
        blockers.append("Inventory fields missing; collect the complete current catalog snapshot")
    if unknown_tables or unknown_objects or inventory.get("functions"):
        blockers.append("Unreviewed objects/functions require a scoped ownership and ACL decision")
    if existing_roles:
        blockers.append("Target role names already exist; bootstrap is not idempotent and must not be replayed")
    blockers += ["Production endpoint, inventory freshness and effective inherited privileges are unverified",
                 "Production backup/recovery, credentials, maintenance window and operator approval remain required"]
    sql_phases = {"bootstrap": bootstrap_sql(expected_database),
                  "grants": [] if unknown_tables else grants_sql(tables),
                  "post_migration_grants_candidate": [] if unknown_tables else grants_sql(sorted(known))}
    return {
        "format_version": 1, "generated_utc": datetime.now(UTC).isoformat(),
        "mode": "offline_dry_run", "inventory_provenance": provenance,
        "production_catalogs_observed": provenance == "production-read-only-catalogs",
        "production_verified": False, "database_connection_attempted": False,
        "database_changes_performed": False, "ready_to_apply": False,
        "inventory": snapshot, "missing_inventory_fields": missing,
        "findings": {"unknown_tables": unknown_tables, "unknown_objects": unknown_objects,
                     "existing_target_roles": existing_roles, "privileged_roles": privileged_roles,
                     "column_acl_reset_required": bool(inventory.get("column_acls"))},
        "blockers": blockers,
        "planned_sql": sql_phases,
        "migration_gate": {"snapshot_tables": sorted(tables),
                           "expected_post_0007_tables": sorted(known),
                           "tables_not_yet_in_snapshot": sorted(known - set(tables)),
                           "revision_not_read_from_catalogs": True,
                           "grants_phase_scope": "Observed tables only, before any approved migrations",
                           "post_migration_grants_candidate_scope": "Review only; never execute until "
                           "approved migrations 0006/0007 finish and a fresh complete inventory matches"},
        "scope": {"automatic_revokes": ["PUBLIC database CONNECT/TEMP/CREATE and public schema rights",
                  "PUBLIC/runtime/backup ACLs on reviewed application tables and every column"],
                  "manual_review_only": ["Old role login, superuser flags and cross-database use",
                  "Inherited memberships and grants to unrelated roles", "Existing default ACL creators",
                  "Unreviewed schemas, functions, views, sequences, foreign tables and extensions"],
                  "never_automatic": ["Passwords or connection changes", "Session termination",
                  "Production migrations", "Ownership assignment of legacy content", "Service restart"]},
        "approval_sequence": ["DBA confirms endpoint and fresh complete inventory",
                  "Approve unknown-object dispositions and exact scoped revokes",
                  "Approve tested encrypted backup/recovery and maintenance window",
                  "DBA reviews bootstrap and table transfers; creates separate credentials privately",
                  "Approve migration-role execution 0005 through 0007 and final grants",
                  "Verify runtime denial tests on clone and read-only production privileges",
                  "Approve runtime connection switch and controlled service restart",
                  "Approve old credential/session retirement and post-cutover acceptance"],
    }


def export_dry_run(inventory_path, output_directory, provenance, expected_database):
    raw = Path(inventory_path).read_bytes()
    inventory = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(inventory, dict):
        raise TypeError("Inventory must be a JSON object")
    report = dry_run_report(inventory, provenance, expected_database)
    report["source_inventory_sha256"] = hashlib.sha256(raw).hexdigest()
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "role-dry-run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["-- REVIEW ONLY: every line is commented; this file performs no operations.",
             "-- Production identity and permission decisions require explicit operator verification."]
    for phase, statements in report["planned_sql"].items():
        lines.append("-- PHASE: " + phase)
        for statement in statements:
            lines.extend("-- " + line for line in (statement + ";").splitlines())
    (destination / "role-plan.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def execute_phase(args):
    engine = create_engine(os.environ["AGENTFLOW_OPERATOR_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            if args.phase == "inventory":
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL search_path = pg_catalog, pg_temp"))
                connection.execute(text("SET LOCAL statement_timeout = '10000ms'"))
            inventory = dict(connection.execute(text(INVENTORY)).mappings().one())
            print(json.dumps(inventory, default=str, indent=2))
            if args.phase == "inventory":
                if args.inventory_output:
                    # Exclusive creation avoids overwriting an existing catalog snapshot.
                    with args.inventory_output.open("x", encoding="utf-8") as output:
                        json.dump(inventory, output, default=str, indent=2)
                        output.write("\n")
                return
            if args.expected_database != inventory["database"]:
                raise ValueError("Expected database identity must match explicitly")
            if not 160000 <= int(inventory["server_version"]) < 170000:
                raise ValueError("PostgreSQL 16 required")
            statements = (bootstrap_sql(args.expected_database) if args.phase == "bootstrap" else
                          grants_sql([t["tablename"] for t in (inventory["tables"] or [])]))
            if not args.apply:
                print(";\n".join(statements) + ";")
                return
            for statement in statements:
                connection.execute(text(statement))
        print("Role phase committed after successful transaction")
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("inventory", "bootstrap", "grants", "plan"), default="inventory", nargs="?")
    parser.add_argument("--expected-database")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--inventory-file", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--inventory-provenance", choices=("synthetic", "operator-supplied", "production-read-only-catalogs"))
    parser.add_argument("--inventory-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.phase == "plan":
            if args.apply or args.inventory_output or not all((args.inventory_file, args.output_directory,
                                      args.inventory_provenance, args.expected_database)):
                raise ValueError("Offline plan requires inventory, provenance, expected database and new output directory")
            report = export_dry_run(args.inventory_file, args.output_directory,
                                    args.inventory_provenance, args.expected_database)
            print(json.dumps({"ok": True, "mode": report["mode"], "ready_to_apply": False,
                              "production_verified": False, "database_connection_attempted": False}))
            return 0
        if args.inventory_file or args.output_directory or args.inventory_provenance:
            raise ValueError("Offline inventory flags require plan phase")
        if args.inventory_output and args.phase != "inventory":
            raise ValueError("Inventory export requires the read-only inventory phase")
        execute_phase(args)
    except Exception:  # noqa: BLE001 - never print DB exceptions, SQL parameters or credential URLs.
        print(json.dumps({"ok": False, "error": "Database role operation failed; "
                          "success was not confirmed. Verify transaction state, target identity, "
                          "PostgreSQL version, connectivity and privileges privately before retry."}),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
