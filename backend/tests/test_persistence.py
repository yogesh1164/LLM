from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import database, main
from app.config import settings


def test_database_readiness_runs_select_one_and_reports_connection_failure(monkeypatch) -> None:
    class Connection:
        def __init__(self) -> None:
            self.statement = None

        def execute(self, statement) -> None:
            self.statement = str(statement)
            assert self.statement == "SELECT 1"

    connection = Connection()

    @contextmanager
    def connected():
        yield connection

    class ReadyEngine:
        connect = staticmethod(connected)

    monkeypatch.setattr(database, "engine", ReadyEngine())
    assert database.database_ready() is True

    class UnavailableEngine:
        def connect(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(database, "engine", UnavailableEngine())
    assert database.database_ready() is False


def test_task_and_agent_stage_persist() -> None:
    task_id = database.create_task("Persist this workflow")
    stage_id = database.start_stage(task_id, "Research")
    database.finish_stage(stage_id, output="Research notes", input_tokens=21, output_tokens=8)
    database.update_task(task_id, status="completed", result={"research": "Research notes"},
                         total_tokens=29, estimated_cost=0.0001)

    row = database.dashboard_data()["history"][0]
    assert row["id"] == task_id
    assert row["status"] == "completed"
    assert row["total_tokens"] == 29
    assert row["stages"][0]["agent"] == "Research"
    assert row["stages"][0]["input_tokens"] == 21
    assert row["stages"][0]["output_tokens"] == 8


def test_task_delete_removes_task_and_cascades_stages() -> None:
    task_id = database.create_task("Delete this workflow")
    stage_id = database.start_stage(task_id, "Research")
    database.finish_stage(stage_id, output="notes", input_tokens=2, output_tokens=3)

    response = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32}).delete(
        f"/api/tasks/{task_id}"
    )
    assert response.status_code == 204
    assert database.get_task(task_id) is None
    with database.SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(database.AgentExecution)) == 0


def test_task_retention_prunes_expired_tasks_and_stages_but_keeps_recent_data(monkeypatch) -> None:
    monkeypatch.setattr(settings, "task_retention_days", 30)
    expired_id = database.create_task("Expired task")
    expired_stage_id = database.start_stage(expired_id, "Research")
    recent_id = database.create_task("Recent task")
    recent_stage_id = database.start_stage(recent_id, "Analysis")
    cutoff = datetime.now(UTC) - timedelta(days=31)
    with database.SessionLocal.begin() as session:
        expired = session.get(database.Task, expired_id)
        expired.created_at = cutoff

    new_id = database.create_task("New task triggers retention")
    assert database.get_task(expired_id) is None
    assert database.get_task(recent_id) is not None
    assert database.get_task(new_id) is not None
    with database.SessionLocal() as session:
        assert session.get(database.AgentExecution, expired_stage_id) is None
        assert session.get(database.AgentExecution, recent_stage_id) is not None


def test_zero_retention_keeps_historical_tasks(monkeypatch) -> None:
    monkeypatch.setattr(settings, "task_retention_days", 0)
    old_id = database.create_task("Historical task")
    with database.SessionLocal.begin() as session:
        session.get(database.Task, old_id).created_at = datetime.now(UTC) - timedelta(days=4000)
    database.create_task("New task")
    assert database.get_task(old_id) is not None
