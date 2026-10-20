"""Mock-only contract tests for independent saved custom workflows."""
from fastapi.testclient import TestClient

from app import custom_workflows, main
from app.custom_agent_schemas import configured_models
from app.providers import StageResult

client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})


def add_agent(name):
    payload = {"name": name, "description": "Test", "role": "Writer",
               "system_instructions": "Produce useful text", "provider": "gemini",
               "model": configured_models("gemini")[0], "temperature": 0.3,
               "max_output_tokens": 300, "enabled": True}
    response = client.post('/api/agents', json=payload)
    assert response.status_code == 201, response.text
    return response.json()['id']


def add_workflow(ids):
    response = client.post('/api/custom-workflows', json={"name": "Marketing workflow",
        "description": "Two stages", "enabled": True, "agent_ids": ids})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_definition_crud_auth_and_validation():
    a = add_agent('Alpha')
    b = add_agent('Beta')
    assert TestClient(main.app).get('/api/custom-workflows').status_code == 401
    assert client.post('/api/custom-workflows', json={"name": "X", "agent_ids": [a, a]}).status_code == 422
    assert client.post('/api/custom-workflows', json={"name": "X", "agent_ids": [str(__import__('uuid').uuid4())]}).status_code == 422
    wid = add_workflow([a, b])
    assert client.get(f'/api/custom-workflows/{wid}').json()['agent_ids'] == [a, b]
    assert len(client.get('/api/custom-workflows').json()) == 1
    response = client.put(f'/api/custom-workflows/{wid}', json={"name": "Reordered", "agent_ids": [b, a]})
    assert response.status_code == 200, response.text
    assert response.json()['agent_ids'] == [b, a]
    assert client.delete(f'/api/custom-workflows/{wid}').status_code == 204
    assert client.get(f'/api/custom-workflows/{wid}').status_code == 404


def test_sequential_execution_and_history(monkeypatch):
    a, b = add_agent('Alpha'), add_agent('Beta')
    wid = add_workflow([a, b])
    calls = []
    async def fake_run(**kwargs):
        calls.append(kwargs['prompt'])
        return StageResult(final_output=f"output {len(calls)}", input_tokens=12, output_tokens=7)
    monkeypatch.setattr(custom_workflows, 'run_custom_gemini_agent', fake_run)
    response = client.post(f'/api/custom-workflows/{wid}/execute', json={'task':'Research links'})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['status'] == 'completed'
    assert run['result'] == 'output 2'
    assert len(run['steps']) == 2 and all(s['status']=='completed' for s in run['steps'])
    assert calls[0] == 'Research links'
    assert 'output 1' in calls[1]
    assert client.get(f"/api/custom-workflows/runs/{run['id']}").json()['result'] == 'output 2'
    assert len(client.get(f'/api/custom-workflows/{wid}/runs').json()) == 1
    assert client.delete(f'/api/custom-workflows/{wid}').status_code == 204
    assert client.get(f"/api/custom-workflows/runs/{run['id']}").json()['status']=='completed'


def test_provider_failure_preserves_partial_result(monkeypatch):
    a, b = add_agent('Alpha'), add_agent('Beta')
    wid = add_workflow([a,b])
    calls = 0
    async def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('secret-provider-error')
        return StageResult(final_output='first output', input_tokens=3, output_tokens=2)
    monkeypatch.setattr(custom_workflows, 'run_custom_gemini_agent', fake_run)
    run = client.post(f'/api/custom-workflows/{wid}/execute', json={'task':'Write overview'}).json()
    assert run['status']=='failed' and run['result']=='first output'
    assert run['steps'][0]['status']=='completed'
    assert run['steps'][1]['status']=='failed'
    assert 'secret-provider-error' not in str(run)


def test_disabled_agent_and_workflow_rejected():
    a = add_agent('Alpha')
    wid = add_workflow([a])
    assert client.patch(f'/api/agents/{a}', json={'enabled':False}).status_code == 200
    assert client.post(f'/api/custom-workflows/{wid}/execute', json={'task':'Do research'}).status_code == 409
    assert client.patch(f'/api/agents/{a}', json={'enabled':True}).status_code == 200
    assert client.put(f'/api/custom-workflows/{wid}', json={'name':'Disabled', 'enabled':False, 'agent_ids':[a]}).status_code == 200
    assert client.post(f'/api/custom-workflows/{wid}/execute', json={'task':'Do research'}).status_code == 409
