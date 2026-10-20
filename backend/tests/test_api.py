from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main

client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})


def test_health_check() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentflow-api"}


def test_dashboard_returns_200() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200


def test_cors_allows_development_origins() -> None:
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        response = client.get("/api/dashboard", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_cors_rejects_disallowed_origin() -> None:
    response = client.get("/api/health", headers={"Origin": "http://localhost:3001"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_headers_survive_internal_server_error(monkeypatch) -> None:
    def fail_dashboard() -> dict:
        raise RuntimeError("database query failed")

    monkeypatch.setattr(main, "dashboard_data", fail_dashboard)
    error_client = TestClient(main.app, raise_server_exceptions=False,
                              headers={"Authorization": "Bearer " + "t" * 32})
    response = error_client.get("/api/dashboard", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_workflow_rejects_oversized_input() -> None:
    response = client.post("/api/workflows/collaborate", json={"task": "x" * 1_001})
    assert response.status_code == 422


def test_missing_selected_provider_key_returns_safe_message(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "ai_provider", "gemini")
    monkeypatch.setattr(main.settings, "gemini_api_key", None)
    response = client.post("/api/workflows/execute", json={"task": "Run without a configured key"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Gemini API key is not configured"


def test_workflow_returns_two_agent_outputs(monkeypatch) -> None:
    async def fake_workflow(task: str, task_id: str) -> dict:
        assert task == "Summarize this"
        return {"research": "Notes", "analysis": "Conclusion", "report": "Report", "review": "Review",
                "sources": [], "total_tokens": 12, "estimated_cost": 0.01}

    monkeypatch.setattr(main.settings, "ai_provider", "openai")
    monkeypatch.setattr(main.settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(main, "run_workflow", fake_workflow)
    response = client.post("/api/workflows/collaborate", json={"task": "Summarize this"})
    assert response.status_code == 200
    assert response.json() == {"research": "Notes", "analysis": "Conclusion"}


def test_execute_workflow_records_results(monkeypatch) -> None:
    async def fake_workflow(task: str, task_id: str, progress=None) -> dict[str, str | list | int | float]:
        assert task == "Prepare a brief"
        return {"research": "R", "analysis": "A", "report": "P", "review": "V", "sources": [],
                "total_tokens": 20, "estimated_cost": 0.02}

    monkeypatch.setattr(main.settings, "ai_provider", "openai")
    monkeypatch.setattr(main.settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(main, "run_workflow", fake_workflow)
    response = client.post("/api/workflows/execute", json={"task": "Prepare a brief"})
    assert response.status_code == 200
    assert response.json() == {
        "task_id": response.json()["task_id"], "status": "completed", "research": "R", "analysis": "A", "report": "P", "review": "V",
        "sources": [], "total_tokens": 20, "estimated_cost": 0.02,
        "provider": None, "model": None, "input_tokens": None, "output_tokens": None,
    }
    dashboard = client.get("/api/dashboard")
    assert dashboard.json()["completed"] == 1
    assert dashboard.json()["history"][0]["status"] == "completed"
    task_id = response.json()["task_id"]
    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["result"]["research"] == "R"


def test_stream_emits_real_stage_events(monkeypatch) -> None:
    async def fake_workflow(task: str, task_id: str, progress=None) -> dict:
        await progress({"type": "stage", "agent": "Research", "status": "running"})
        await progress({"type": "stage", "agent": "Research", "status": "completed"})
        return {"research": "R", "analysis": "A", "report": "P", "review": "V", "sources": [],
                "total_tokens": 10, "estimated_cost": 0.001}

    monkeypatch.setattr(main.settings, "ai_provider", "openai")
    monkeypatch.setattr(main.settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(main, "run_workflow", fake_workflow)
    with client.stream("POST", "/api/workflows/stream", json={"task": "Stream this task"}) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert '"agent": "Research", "status": "running"' in body
    assert '"type": "result"' in body

