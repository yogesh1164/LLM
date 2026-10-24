"""Read-only release evidence. Defaults to an offline plan; never starts services.

Run with the backend Python environment. No dotenv file is selected implicitly.
JSON output deliberately contains no URLs, passwords, environment values or SQL errors.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def configuration(values):
    from sqlalchemy.engine import make_url
    errors = []
    if any("${" in str(value) for value in values.values()):
        errors.append("Configuration contains unexpanded interpolation placeholders")
    provider = values.get("AI_PROVIDER", "gemini")
    key_name = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
    if not key_name or not str(values.get(key_name) or "").strip():
        errors.append("Selected provider and its API key must be configured")
    try:
        url = make_url(values.get("DATABASE_URL", ""))
        if (url.drivername not in {"postgresql", "postgresql+psycopg"}
                or not url.host or not url.database or not url.username):
            raise ValueError("Invalid database URL")
        if values.get("AUTH_MODE") == "accounts" and url.username != "agentflow_runtime":
            raise ValueError("Accounts backend requires the reviewed runtime role")
    except Exception:  # noqa: BLE001 - URL parser exceptions can contain secrets.
        errors.append("PostgreSQL runtime DATABASE_URL must be configured with the intended runtime role")
    if values.get("APP_ENV") != "production":
        errors.append("APP_ENV must explicitly select production")
    if values.get("AUTH_MODE", "legacy_bearer") not in {"accounts", "legacy_bearer"}:
        errors.append("AUTH_MODE is invalid")
    if values.get("DURABLE_EXECUTION_ENABLED", "false").lower() not in {"true", "false"}:
        errors.append("DURABLE_EXECUTION_ENABLED must be true or false")
    origins = values.get("FRONTEND_ORIGINS", "").split(",")
    try:
        valid_origins = all(
            (p := urlsplit(origin.strip())).scheme == "https" and p.hostname
            and not (p.username or p.password or p.path or p.query or p.fragment)
            and "*" not in origin and not any(c.isspace() for c in origin.strip())
            and (p.port is None or 1 <= p.port <= 65535) for origin in origins
        )
    except ValueError:
        valid_origins = False
    if not valid_origins:
        errors.append("FRONTEND_ORIGINS must contain exact HTTPS origins")
    if values.get("AUTH_MODE", "legacy_bearer") == "legacy_bearer" and len(values.get("API_ACCESS_TOKEN", "")) < 32:
        errors.append("Legacy bearer token is missing or too short")
    return {"configuration_valid": not errors, "errors": errors,
            "accounts_enabled": values.get("AUTH_MODE") == "accounts",
            "durable_enabled": values.get("DURABLE_EXECUTION_ENABLED", "false").lower() == "true"}


def database(url, expected_database, expected_user):
    from sqlalchemy import create_engine, text
    engine = create_engine(url, connect_args={"connect_timeout": 5}, echo=False)
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            identity = connection.execute(text("SELECT current_database(), current_user")).one()
            if tuple(identity) != (expected_database, expected_user):
                raise ValueError("Database identity mismatch")
            role = connection.execute(text("""SELECT rolsuper, rolcreaterole, rolcreatedb,
                rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user""")).one()
            rights = connection.execute(text("""SELECT
                has_database_privilege(current_database(), 'CREATE'),
                has_database_privilege(current_database(), 'TEMP'),
                has_schema_privilege('public', 'CREATE'),
                EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public'
                    AND tableowner = current_user)""")).one()
            protected_rights = connection.execute(text("""SELECT
                EXISTS (SELECT 1 FROM pg_auth_members
                    WHERE member = current_user::regrole AND set_option),
                has_column_privilege('public.users', 'role', 'UPDATE'),
                has_column_privilege('public.users', 'enabled', 'UPDATE'),
                has_table_privilege('public.ownership_assignments', 'INSERT,UPDATE,DELETE'),
                has_table_privilege('public.alembic_version', 'INSERT,UPDATE,DELETE'),
                EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public'
                    AND has_table_privilege(format('%I.%I', schemaname, tablename), 'TRUNCATE'))
                """)).one()
            revision = connection.scalars(text("SELECT version_num FROM public.alembic_version")).all()
            search_path = connection.scalar(text("SHOW search_path"))
            secure_role = not any(role) and not any(rights) and not any(protected_rights)
            return {"identity_confirmed": True, "read_only": True,
                    "least_privilege": secure_role, "revision": revision,
                    "expected_revision": revision == ["0007_accounts_ownership"],
                    "search_path_hardened": search_path.replace('"', '').replace(' ', '')
                    in {"public,pg_temp", "pg_catalog,public,pg_temp"}}
    finally:
        engine.dispose()


def image(reference):
    result = subprocess.run(["docker", "image", "inspect", reference], capture_output=True,
                            text=True, timeout=30, check=True)
    item = json.loads(result.stdout)[0]
    runtime_user = (item["Config"].get("User") or "").split(":", 1)[0]
    return {"id": item["Id"], "repository_digests": item.get("RepoDigests", []),
            "nonroot_user": runtime_user not in ("", "0", "root"),
            "healthcheck_present": bool(item["Config"].get("Healthcheck"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--database-env-var", help="Explicit environment variable containing the target URL")
    parser.add_argument("--expected-database")
    parser.add_argument("--expected-user")
    parser.add_argument("--image", action="append", default=[])
    options = parser.parse_args(argv)
    report = {"read_only": True, "production_changes": False, "checks": {}}
    try:
        if options.env_file:
            from dotenv import dotenv_values
            report["checks"]["configuration"] = configuration(dict(dotenv_values(options.env_file, interpolate=False)))
        if options.database_env_var:
            if not options.expected_database or not options.expected_user:
                raise ValueError("Explicit database and role identities are required")
            report["checks"]["database"] = database(os.environ[options.database_env_var], options.expected_database, options.expected_user)
        image_results = [image(reference) for reference in options.image]
        if image_results:
            report["checks"]["images"] = image_results
        report["mode"] = "inspection" if report["checks"] else "offline_plan"
        failed = any(item is False for check in report["checks"].values()
                     if isinstance(check, dict) for key, item in check.items()
                     if key not in {"accounts_enabled", "durable_enabled"})
        failed = failed or any(not item["nonroot_user"] or not item["healthcheck_present"]
                               for item in image_results)
        report["inspection_passed"] = not failed
        report["release_approved"] = False
        print(json.dumps(report, indent=2))
        return int(failed)
    except Exception:  # noqa: BLE001 - prevent credentials and SQL errors reaching logs.
        print(json.dumps({"inspection_passed": False, "error": "Preflight failed; inspect inputs and target through an authorized session. No credentials are included."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
