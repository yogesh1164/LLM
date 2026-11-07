"""New per-test schemas inside the explicitly named disposable PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, text

from app import legacy_ownership
from tests.test_durable_postgres import legacy_history
from tests.test_durable_postgres import postgres as postgres_fixture
from tests.test_ownership_mapping import exercise_mapping, seed_mapping_data
from tests.test_ownership_mapping import (
    test_mapping_failures_never_partially_assign as exercise_failure,
)

postgres = postgres_fixture


@pytest.mark.parametrize("postgres", ["head"], indirect=True)
def test_postgres_explicit_multiaccount_mapping_and_quarantine(postgres, monkeypatch):
    exercise_mapping(monkeypatch)


@pytest.mark.parametrize("postgres", ["head"], indirect=True)
@pytest.mark.parametrize("failure", ["stale", "rollback", "wrong-digest"])
def test_postgres_mapping_transaction_guards(postgres, failure):
    exercise_failure(failure)


@pytest.mark.parametrize("postgres", ["head"], indirect=True)
def test_postgres_concurrent_apply_is_once_and_audited(postgres):
    engine, _, _, manifest, _, _, _ = seed_mapping_data()
    barrier = Barrier(2)

    def worker():
        barrier.wait(timeout=10)
        with engine.begin() as connection:
            return legacy_ownership.apply_mapping(connection, manifest,
                confirm_digest=manifest["manifest_digest"], approved_by="synthetic-concurrent-approval")

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: worker(), range(2))) == [0, 6]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM ownership_assignments")) == 2
        assert legacy_ownership.verify_mapping(connection, manifest)["assigned_roots"] == 6


@pytest.mark.parametrize("postgres", ["0005_custom_workflows", "0006_durable_executions"], indirect=True)
def test_postgres_preaccount_inventory_never_modifies_schema_or_records(postgres):
    legacy_history()
    with postgres.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        before = {name: [(column["name"], str(column["type"]), column["nullable"], column["default"])
                        for column in inspect(connection).get_columns(name)]
                  for name in inspect(connection).get_table_names()}
        result = legacy_ownership.inventory_before_accounts(connection)
        after = {name: [(column["name"], str(column["type"]), column["nullable"], column["default"])
                       for column in inspect(connection).get_columns(name)]
                 for name in inspect(connection).get_table_names()}
        assert before == after
        assert result["virtual_null_owners"] and not result["mappings_available"]
        assert result["accounts"] == [] and "users" not in before
        assert len(result["tables"]) == (9 if result["revision"] == "0005_custom_workflows" else 10)
        assert "Offline legacy task" not in str(result)
