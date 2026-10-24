"""Offline persistence contracts; crash recovery does not imply safe replay."""

import asyncio
import os
import subprocess
import sys
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import custom_workflows, database, main, workflow
from app.custom_workflow_schemas import WorkflowRunInput
from app.providers import StageResult
from tests.test_custom_workflows import add_agent, add_workflow, client


@pytest.mark.parametrize("interrupted_position", [0, 1, 2])
@pytest.mark.parametrize("interruption", ["cancel", "timeout", "busy"])
def test_custom_workflow_interruption_preserves_history_without_replay(
    monkeypatch, interrupted_position, interruption,
):
    from app.provider_capacity import ProviderBusyError

    wid = add_workflow([add_agent(name) for name in ("First", "Second", "Third")])
    calls = []
    entered = asyncio.Event()

    async def provider(**kwargs):
        position = len(calls)
        calls.append(kwargs["name"])
        if position == interrupted_position:
            if interruption == "busy":
                raise ProviderBusyError("private-provider-details")
            if interruption == "timeout":
                raise TimeoutError("private-provider-details")
            entered.set()
            await asyncio.Event().wait()
        return StageResult(final_output=f"output-{position}", input_tokens=3, output_tokens=2)

    monkeypatch.setattr(custom_workflows, "run_custom_gemini_agent", provider)

    async def execute():
        execution = asyncio.create_task(custom_workflows.execute_definition(
            UUID(wid), WorkflowRunInput(task="Offline interruption test")))
        if interruption == "cancel":
            await asyncio.wait_for(entered.wait(), timeout=2)
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
        else:
            await asyncio.wait_for(execution, timeout=2)

    asyncio.run(execute())
    status = {"cancel": "cancelled", "timeout": "timed_out", "busy": "failed"}[interruption]
    with database.SessionLocal() as session:
        run_id = session.scalar(select(database.CustomWorkflowRun.id))
    # Fresh API sessions must recover the stored history without calling AI.
    for _ in range(2):
        response = client.get(f"/api/custom-workflows/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        assert run["status"] == status and run["completed_at"] is not None
        assert run["result"] == (f"output-{interrupted_position - 1}" if interrupted_position else None)
        assert [step["status"] for step in run["steps"]] == (
            ["completed"] * interrupted_position + [status] + ["pending"] * (2 - interrupted_position))
        assert all(step["output"] == f"output-{i}"
                   and step["input_tokens"] == 3 and step["output_tokens"] == 2
                   for i, step in enumerate(run["steps"][:interrupted_position]))
        assert "private-provider-details" not in response.text
    assert len(calls) == interrupted_position + 1


@pytest.mark.parametrize("interrupted_position", [0, 1, 4])
def test_request_cancellation_closes_active_stage_and_preserves_completed_outputs(
    monkeypatch, interrupted_position,
):
    names = ("orchestrator", "research", "analysis", "report", "review")
    monkeypatch.setattr(workflow, "build_agents", lambda: dict(zip(names, names)))
    calls = []
    entered = asyncio.Event()

    async def provider(agent, prompt, **kwargs):
        calls.append(agent)
        if agent == names[interrupted_position]:
            entered.set()
            await asyncio.Event().wait()
        return StageResult(agent, input_tokens=3, output_tokens=2)

    monkeypatch.setattr(workflow, "run_agent_stage", provider)

    async def execute():
        execution = asyncio.create_task(main._execute("Offline cancellation"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution

    asyncio.run(execute())
    task = database.dashboard_data()["history"][0]
    stored = database.get_task(task["id"])
    assert stored["status"] == "failed" and stored["error"] == "Workflow cancelled"
    assert [stage["status"] for stage in stored["stages"]].count("completed") == interrupted_position
    assert [stage["status"] for stage in stored["stages"]].count("cancelled") == 1
    assert stored["total_tokens"] == (5 * interrupted_position if interrupted_position else None)
    assert calls == list(names[:interrupted_position + 1])


@pytest.mark.parametrize("interrupt", ["cancel", "error"])
def test_interrupted_progress_callback_does_not_leave_running_stage(monkeypatch, interrupt):
    task_id = database.create_task("Offline progress interruption")
    monkeypatch.setattr(workflow, "build_agents", lambda: {"orchestrator": "orchestrator"})

    async def no_provider(*args, **kwargs):
        pytest.fail("Interrupted progress must prevent provider invocation")

    monkeypatch.setattr(workflow, "run_agent_stage", no_provider)

    async def progress(event):
        if event.get("type") == "stage" and event["status"] == "running":
            if interrupt == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("Transport disconnected")

    expected = asyncio.CancelledError if interrupt == "cancel" else RuntimeError
    with pytest.raises(expected):
        asyncio.run(workflow.run_workflow("Offline progress interruption", task_id, progress))
    stored = database.get_task(task_id)
    assert stored["stages"][0]["status"] == ("cancelled" if interrupt == "cancel" else "failed")
    with database.SessionLocal() as session:
        stage = session.scalar(select(database.AgentExecution).where(
            database.AgentExecution.task_id == task_id))
        assert stage.completed_at is not None


@pytest.mark.parametrize("interrupt", ["cancel", "error"])
@pytest.mark.parametrize("completed_position", [0, 1, 4])
def test_progress_interruption_preserves_committed_stage(monkeypatch, interrupt, completed_position):
    task_id = database.create_task("Offline completed progress interruption")
    names = ("orchestrator", "research", "analysis", "report", "review")
    monkeypatch.setattr(workflow, "build_agents", lambda: dict(zip(names, names)))
    calls = []

    async def provider(agent, prompt, **kwargs):
        calls.append(agent)
        return StageResult(f"output-{agent}", input_tokens=3, output_tokens=2)

    monkeypatch.setattr(workflow, "run_agent_stage", provider)

    async def progress(event):
        if (event.get("type") == "stage" and event["status"] == "completed"
                and event["agent"].lower() == names[completed_position]):
            if interrupt == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("Transport disconnected")

    expected = asyncio.CancelledError if interrupt == "cancel" else RuntimeError
    with pytest.raises(expected):
        asyncio.run(workflow.run_workflow("Offline interruption", task_id, progress))
    for _ in range(2):
        stored = database.get_task(task_id)
        assert [stage["status"] for stage in stored["stages"]] == (
            ["completed"] * (completed_position + 1))
        assert stored["total_tokens"] == 5 * (completed_position + 1)
        key = "plan" if completed_position == 0 else names[completed_position]
        assert stored["result"][key] == f"output-{names[completed_position]}"
    assert calls == list(names[:completed_position + 1])


def test_process_exit_preserves_committed_partial_steps_and_does_not_auto_replay(tmp_path, monkeypatch):
    """A fresh process/session can read crash remnants; leases are still needed.

    The child deliberately exits without cleanup after committing a completed
    step and starting the next. No provider is imported or called by that script.
    """
    db_url = "sqlite:///" + (tmp_path / "crash.sqlite").as_posix()
    script = '''
import os
from app import database as db
db.Base.metadata.create_all(db.engine)
task_id = db.create_task("Offline crash fixture")
stage_id = db.start_stage(task_id, "Research")
db.finish_stage(stage_id, output="committed output", input_tokens=3, output_tokens=2)
db.update_task(task_id, status="running", result={"research": "committed output"}, total_tokens=5)
db.start_stage(task_id, "Analysis")
os._exit(23)
'''
    env = {**os.environ, "DATABASE_URL": db_url, "APP_ENV": "development",
           "GEMINI_API_KEY": "offline-test-placeholder"}
    result = subprocess.run([sys.executable, "-c", script], check=False,
                            env=env, capture_output=True, timeout=15)
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    engine = create_engine(db_url)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    try:
        def no_replay(*args, **kwargs):
            pytest.fail("Reading crash history must not invoke a provider")

        monkeypatch.setattr(workflow, "run_agent_stage", no_replay)
        with database.SessionLocal() as session:
            task_id = session.scalar(select(database.Task.id))
        for _ in range(2):
            task = client.get(f"/api/tasks/{task_id}").json()
            assert task["status"] == "running"  # Characterizes the unresolved lease/recovery gap.
            assert task["result"] == {"research": "committed output"}
            assert task["total_tokens"] == 5
            assert sorted(stage["status"] for stage in task["stages"]) == ["completed", "running"]
    finally:
        engine.dispose()
