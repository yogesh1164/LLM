import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import database, main, workflow
from app.providers import StageResult


def test_workflow_completes_five_mocked_stages(monkeypatch):
    task_id = database.create_task("test task")
    monkeypatch.setattr(workflow, "build_agents", lambda: {name: name for name in
                        ("orchestrator", "research", "analysis", "report", "review")})
    calls = []

    async def mock_stage(agent, prompt, **kwargs):
        calls.append(agent)
        return StageResult(agent, input_tokens=2, output_tokens=1)

    monkeypatch.setattr(workflow, "run_agent_stage", mock_stage)
    result = asyncio.run(workflow.run_workflow("test task", task_id))
    assert calls == ["orchestrator", "research", "analysis", "report", "review"]
    assert result["review"] == "review"
    assert result["total_tokens"] == 15
    assert all(stage["status"] == "completed" and stage["elapsed_ms"] is not None
               for stage in database.get_task(task_id)["stages"])


def test_stage_timeout_is_recorded_without_retry(monkeypatch):
    task_id = database.create_task("test task")
    monkeypatch.setattr(workflow.settings, "agent_timeout_seconds", 0.01)
    monkeypatch.setattr(workflow, "build_agents", lambda: {"orchestrator": "orchestrator"})
    calls = 0

    async def slow_stage(agent, prompt, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    monkeypatch.setattr(workflow, "run_agent_stage", slow_stage)
    events = []

    async def progress(event):
        events.append(event)

    with pytest.raises(workflow.StageTimeoutError, match="Orchestrator exceeded"):
        asyncio.run(workflow.run_workflow("test task", task_id, progress))
    stage = database.get_task(task_id)["stages"][0]
    assert stage["status"] == "timed_out"
    assert stage["elapsed_ms"] is not None
    assert calls == 1
    assert any(event.get("status") == "timed_out" for event in events)


def test_total_workflow_timeout_preserves_partial_results_and_closes_running_stage(monkeypatch):
    monkeypatch.setattr(main.settings, "ai_provider", "openai")
    monkeypatch.setattr(main.settings, "openai_api_key", SecretStr("mock"))
    monkeypatch.setattr(main.settings, "workflow_timeout_seconds", 0.01)

    async def blocked(task, task_id, progress=None):
        database.update_task(task_id, status="running", result={"report": "completed draft"})
        database.start_stage(task_id, "Review")
        await asyncio.sleep(1)

    monkeypatch.setattr(main, "run_workflow", blocked)
    test_client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})
    response = test_client.post("/api/workflows/execute", json={"task": "test timeout"})
    assert response.status_code == 504
    task = database.dashboard_data()["history"][0]
    assert task["status"] == "failed"
    assert "total timeout" in task["error"]
    detail = test_client.get(f"/api/tasks/{task['id']}").json()
    assert detail["result"]["report"] == "completed draft"
    assert detail["stages"][0]["status"] == "timed_out"


def test_sse_reports_stage_failure_and_error_detail(monkeypatch):
    monkeypatch.setattr(main.settings, "ai_provider", "openai")
    monkeypatch.setattr(main.settings, "openai_api_key", SecretStr("mock"))

    async def failed(task, task_id, progress=None):
        stage_id = database.start_stage(task_id, "Review")
        database.fail_stage(stage_id, "Review provider request failed", status="failed", elapsed_ms=25)
        await progress({"type": "stage", "agent": "Review", "status": "failed",
                        "error": "Review provider request failed", "elapsed_ms": 25})
        raise RuntimeError("Review provider request failed")

    monkeypatch.setattr(main, "run_workflow", failed)
    test_client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})
    with test_client.stream("POST", "/api/workflows/stream", json={"task": "test SSE error"}) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert '"agent": "Review", "status": "failed"' in body
    assert '"type": "error"' in body
    assert "Review provider request failed" in body


def test_partial_stage_outputs_persist_when_later_stage_fails(monkeypatch):
    task_id = database.create_task("test partial")
    names = ("orchestrator", "research", "analysis", "report", "review")
    monkeypatch.setattr(workflow, "build_agents", lambda: {name: name for name in names})

    async def mock_stage(agent, prompt, **kwargs):
        if agent == "review":
            raise RuntimeError("review unavailable")
        return StageResult(f"{agent} output")

    monkeypatch.setattr(workflow, "run_agent_stage", mock_stage)
    with pytest.raises(RuntimeError, match="review unavailable"):
        asyncio.run(workflow.run_workflow("test partial", task_id))
    task = database.get_task(task_id)
    assert task["result"]["report"] == "report output"
    assert task["result"].get("review") is None
    assert [stage["status"] for stage in task["stages"]] == [
        "completed", "completed", "completed", "completed", "failed"
    ]


def test_stage_timeouts_are_configurable_and_review_gets_more_time(monkeypatch):
    task_id = database.create_task("test stage budgets")
    monkeypatch.setattr(workflow, "build_agents", lambda: {
        name: name for name in ("orchestrator", "research", "analysis", "report", "review")
    })
    monkeypatch.setattr(workflow.settings, "agent_timeout_seconds", 90)
    monkeypatch.setattr(workflow.settings, "review_timeout_seconds", 180)
    timeouts = []

    async def mock_stage(agent, prompt, *, timeout_seconds, on_retry=None):
        timeouts.append(timeout_seconds)
        return StageResult(agent)

    monkeypatch.setattr(workflow, "run_agent_stage", mock_stage)
    asyncio.run(workflow.run_workflow("test stage budgets", task_id))
    assert timeouts == [90, 90, 90, 90, 180]


def test_cancelled_stage_is_recorded_with_duration_and_partial_outputs(monkeypatch):
    task_id = database.create_task("test cancellation")
    monkeypatch.setattr(workflow, "build_agents", lambda: {
        name: name for name in ("orchestrator", "research", "analysis", "report", "review")
    })

    async def mock_stage(agent, prompt, **kwargs):
        if agent == "review":
            await asyncio.Event().wait()
        return StageResult(f"{agent} output")

    monkeypatch.setattr(workflow, "run_agent_stage", mock_stage)
    events = []

    async def collect(event):
        events.append(event)

    async def cancel_workflow():
        task = asyncio.create_task(workflow.run_workflow("test cancellation", task_id, collect))
        while len(database.get_task(task_id)["stages"]) < 5:
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_workflow())
    task = database.get_task(task_id)
    assert task["result"]["report"] == "report output"
    assert task["stages"][-1]["status"] == "cancelled"
    assert task["stages"][-1]["elapsed_ms"] is not None
    assert any(event.get("status") == "cancelled" for event in events)
