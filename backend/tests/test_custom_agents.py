from fastapi.testclient import TestClient

from app import main
from app.custom_agent_schemas import configured_models

client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})


def payload(name: str = "Fact Checker") -> dict:
    return {
        "name": name,
        "description": "Checks claims against supplied evidence.",
        "role": "Evidence reviewer",
        "system_instructions": "Identify unsupported claims and explain why.",
        "provider": "gemini",
        "model": configured_models("gemini")[0],
        "temperature": 0.2,
        "max_output_tokens": 2048,
        "enabled": True,
    }


def test_agent_options_and_empty_listing() -> None:
    options = client.get("/api/agents/options")
    assert options.status_code == 200
    assert options.json()["providers"] == [
        {"provider": "gemini", "models": configured_models("gemini")},
        {"provider": "openai", "models": configured_models("openai")},
    ]
    assert client.get("/api/agents").json() == []


def test_agent_mutations_allow_frontend_cors_preflight() -> None:
    response = client.options("/api/agents/", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_agent_create_list_retrieve_update_and_persist() -> None:
    created = client.post("/api/agents", json=payload())
    assert created.status_code == 201
    agent = created.json()
    assert agent["name"] == "Fact Checker"
    assert "api_key" not in agent
    agent_id = agent["id"]

    listed = client.get("/api/agents")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == agent_id
    retrieved = client.get(f"/api/agents/{agent_id}")
    assert retrieved.json()["system_instructions"] == payload()["system_instructions"]

    updated = client.patch(f"/api/agents/{agent_id}", json={"description": "Updated", "enabled": False})
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated"
    assert updated.json()["enabled"] is False
    assert client.get(f"/api/agents/{agent_id}").json()["enabled"] is False


def test_duplicate_gets_unique_name_and_retains_configuration() -> None:
    original = client.post("/api/agents", json=payload("Verifier")).json()
    first = client.post(f"/api/agents/{original['id']}/duplicate")
    second = client.post(f"/api/agents/{original['id']}/duplicate")
    assert first.status_code == second.status_code == 201
    assert first.json()["name"] == "Verifier (Copy)"
    assert second.json()["name"] == "Verifier (Copy 2)"
    assert second.json()["system_instructions"] == original["system_instructions"]


def test_delete_custom_agent_and_missing_agent() -> None:
    agent = client.post("/api/agents", json=payload()).json()
    deleted = client.delete(f"/api/agents/{agent['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/agents/{agent['id']}").status_code == 404


def test_validation_and_case_insensitive_unique_names() -> None:
    invalid = payload()
    invalid["system_instructions"] = "  "
    assert client.post("/api/agents", json=invalid).status_code == 422
    assert client.post("/api/agents", json={**payload(), "temperature": 3}).status_code == 422
    assert client.post("/api/agents", json={**payload(), "max_output_tokens": 0}).status_code == 422
    assert client.post("/api/agents", json={**payload(), "provider": "unknown"}).status_code == 422
    assert client.post("/api/agents", json={**payload(), "model": "unconfigured-model"}).status_code == 422
    saved = client.post("/api/agents", json=payload("Patch validation")).json()
    assert client.patch(f"/api/agents/{saved['id']}", json={"name": "  "}).status_code == 422
    assert client.patch(f"/api/agents/{saved['id']}", json={"provider": "openai"}).status_code == 422
    assert client.post("/api/agents", json=payload("Unique Name")).status_code == 201
    duplicate = client.post("/api/agents", json=payload("unique name"))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "An agent with that name already exists"
    assert client.post("/api/agents", json=payload("Research")).status_code == 409


def test_builtin_agents_are_protected_from_all_mutations() -> None:
    agent_id = "Research"
    assert client.get(f"/api/agents/{agent_id}").status_code == 403
    assert client.patch(f"/api/agents/{agent_id}", json={"enabled": False}).status_code == 403
    assert client.post(f"/api/agents/{agent_id}/duplicate").status_code == 403
    assert client.delete(f"/api/agents/{agent_id}").status_code == 403
