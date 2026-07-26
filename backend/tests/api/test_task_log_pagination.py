from conftest import auth_headers


def test_task_detail_paginates_log_entries(client, db_session_factory):
    from app.models import AgentLog, AgentStep
    from app.models.common import StepStatus

    headers = auth_headers(client, email="task-log-page@example.com", display_name="TLP")
    task_id = client.post(
        "/tasks",
        json={"idea": "paginate task logs", "asset_ids": []},
        headers=headers,
    ).json()["task_id"]

    db = db_session_factory()
    step = AgentStep(
        task_id=task_id,
        seq=1,
        agent="GameCodeAgent",
        name="Code Generation",
        status=StepStatus.RUNNING,
    )
    db.add(step)
    db.flush()
    db.add_all(
        [AgentLog(step_id=step.id, seq=index, line=f"log-{index}") for index in range(5)]
    )
    db.commit()
    db.close()

    page = client.get(f"/tasks/{task_id}?logs_limit=2", headers=headers)
    assert page.status_code == 200
    body = page.json()
    assert [entry["line"] for entry in body["logs"][0]["entries"]] == ["log-3", "log-4"]
    assert body["steps"][0]["logs"] == ["log-3", "log-4"]
    assert body["logs_page"] == {
        "limit": 2,
        "before": None,
        "next_before": body["logs"][0]["entries"][0]["cursor"],
        "has_more": True,
        "total": 5,
        "returned": 2,
    }

    older = client.get(
        f"/tasks/{task_id}?logs_limit=2&logs_before={body['logs_page']['next_before']}",
        headers=headers,
    )
    assert older.status_code == 200
    older_body = older.json()
    assert [entry["line"] for entry in older_body["logs"][0]["entries"]] == ["log-1", "log-2"]
    assert older_body["logs_page"]["has_more"] is True
