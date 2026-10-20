from app import database


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
