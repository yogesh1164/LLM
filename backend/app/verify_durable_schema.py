"""Read-only operator verification; never migrates, stamps or repairs a schema."""

import json
import sys

from sqlalchemy import Boolean, DateTime, String, Uuid, inspect, text

from app import database as db


def verify_schema(engine) -> dict:
    with engine.connect() as connection, connection.begin():
        if connection.dialect.name != "postgresql":
            raise ValueError("PostgreSQL is required for rollout verification")
        connection.execute(text("SET TRANSACTION READ ONLY"))
        inspector = inspect(connection)
        revisions = connection.scalars(text("SELECT version_num FROM alembic_version")).all()
        if revisions not in (["0006_durable_executions"], ["0007_accounts_ownership"]):
            raise ValueError("Expected verified durable/account revision")
        has_accounts = revisions == ["0007_accounts_ownership"]
        columns = {column["name"]: column for column in inspector.get_columns("durable_executions")}
        expected_columns = set(db.DurableExecution.__table__.columns.keys()) - {"owner_id"}
        if has_accounts:
            expected_columns.add("owner_id")
        if set(columns) != expected_columns:
            raise ValueError("Unexpected execution journal columns")
        for model_column in db.DurableExecution.__table__.columns:
            if model_column.name == "owner_id" and not has_accounts:
                continue
            actual = columns[model_column.name]
            expected_type = next(kind for kind in (String, DateTime, Boolean, Uuid)
                                 if isinstance(model_column.type, kind))
            if (not isinstance(actual["type"], expected_type)
                    or actual["nullable"] != model_column.nullable
                    or getattr(actual["type"], "length", None) != getattr(model_column.type, "length", None)
                    or getattr(actual["type"], "timezone", None) != getattr(model_column.type, "timezone", None)):
                raise ValueError("Execution journal column contract mismatch")
        if inspector.get_pk_constraint("durable_executions")["constrained_columns"] != ["id"]:
            raise ValueError("Execution journal primary key mismatch")
        uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("durable_executions")}
        if uniques != {("scope", "key_digest"), ("task_id",), ("agent_execution_id",), ("workflow_run_id",)}:
            raise ValueError("Execution journal uniqueness mismatch")
        fks = {(tuple(item["constrained_columns"]), item["referred_table"],
                tuple(item["referred_columns"]), item["options"].get("ondelete"))
               for item in inspector.get_foreign_keys("durable_executions")}
        expected_fks = {(("task_id",), "tasks", ("id",), "SET NULL"),
                   (("agent_execution_id",), "custom_agent_executions", ("id",), "SET NULL"),
                   (("workflow_run_id",), "custom_workflow_runs", ("id",), "SET NULL")}
        if has_accounts:
            expected_fks.add((("owner_id",), "users", ("id",), "RESTRICT"))
        if fks != expected_fks:
            raise ValueError("Execution journal foreign key mismatch")
        checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints("durable_executions")}
        if set(checks) != {"ck_durable_state", "ck_durable_one_target"}:
            raise ValueError("Execution journal checks missing")
        if not all(state in checks["ck_durable_state"] for state in ("running", "completed", "failed", "interrupted")):
            raise ValueError("Execution state constraint mismatch")
        if not all(field in checks["ck_durable_one_target"] for field in ("task_id", "agent_execution_id", "workflow_run_id")):
            raise ValueError("Execution target constraint mismatch")
        indexes = inspector.get_indexes("durable_executions")
        if not any(item["name"] == "ix_durable_expiry" and item["column_names"] == ["state", "lease_expires_at"] for item in indexes):
            raise ValueError("Execution expiry index mismatch")
        invalid = connection.scalar(text("""
            SELECT count(*) FROM pg_constraint
            WHERE conrelid = 'durable_executions'::regclass
              AND (NOT convalidated OR condeferrable)
        """))
        invalid_index = connection.scalar(text("""
            SELECT count(*) FROM pg_index
            WHERE indrelid = 'durable_executions'::regclass AND NOT indisvalid
        """))
        if invalid or invalid_index:
            raise ValueError("Execution journal has unvalidated constraints/indexes")
        return {"schema_verified": True, "revision": revisions[0], "columns": len(columns),
                "unique_constraints": len(uniques), "foreign_keys": len(fks), "read_only": True}


if __name__ == "__main__":
    try:
        print(json.dumps(verify_schema(db.engine)))
    except Exception:  # noqa: BLE001 - do not print connection strings, credentials or SQL errors.
        print("Durable schema verification failed; inspect the schema/database using an authorized session.", file=sys.stderr)
        raise SystemExit(1) from None
