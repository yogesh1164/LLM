"""Reviewable PostgreSQL 16 role SQL. Default action is read-only inventory.

Run with backend's Python environment. No passwords are accepted or printed.
Use a libpq service / protected passfile via AGENTFLOW_OPERATOR_DATABASE_URL.
"""
import argparse
import json
import os
import re
import sys

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
       (SELECT json_agg(s) FROM (SELECT nspname, pg_get_userbyid(nspowner) AS owner,
          nspacl::text AS acl FROM pg_namespace WHERE nspname='public') s) AS schemas,
       (SELECT json_agg(m) FROM (SELECT pg_get_userbyid(roleid) AS role,
          pg_get_userbyid(member) AS member, admin_option, inherit_option, set_option
          FROM pg_auth_members) m) AS memberships,
       (SELECT json_agg(a) FROM (SELECT pg_get_userbyid(defaclrole) AS creator,
          defaclobjtype, defaclacl::text AS acl FROM pg_default_acl) a) AS defaults,
       (SELECT json_agg(r) FROM (SELECT rolname, rolsuper, rolcreatedb, rolcreaterole,
          rolreplication, rolbypassrls, rolcanlogin FROM pg_roles
          WHERE rolname LIKE 'agentflow_%') r) AS roles,
       (SELECT json_agg(t) FROM (SELECT tablename, tableowner FROM pg_tables
          WHERE schemaname = 'public') t) AS tables,
       (SELECT json_agg(a) FROM (SELECT c.relname AS table_name, a.attname AS column_name,
          a.attacl::text AS acl FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
          AND a.attnum > 0 AND NOT a.attisdropped AND a.attacl IS NOT NULL) a) AS column_acls
"""


def execute_phase(args):
    engine = create_engine(os.environ["AGENTFLOW_OPERATOR_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            inventory = dict(connection.execute(text(INVENTORY)).mappings().one())
            print(json.dumps(inventory, default=str, indent=2))
            if args.phase == "inventory":
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
    parser.add_argument("phase", choices=("inventory", "bootstrap", "grants"), default="inventory", nargs="?")
    parser.add_argument("--expected-database")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
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
