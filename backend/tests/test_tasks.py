def _auth(client):
    token = client.post(
        "/auth/register",
        json={"email": "t@t.com", "password": "secret1", "display_name": "T"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_task(client):
    h = _auth(client)
    r = client.post("/tasks", json={"idea": "a platformer", "asset_ids": []}, headers=h)
    assert r.status_code == 200
    tid = r.json()["task_id"]
    items = client.get("/tasks", headers=h).json()["items"]
    assert any(t["id"] == tid for t in items)


def test_delete_active_task_rejected(client):
    h = _auth(client)
    tid = client.post("/tasks", json={"idea": "x", "asset_ids": []}, headers=h).json()["task_id"]
    # 任务创建后处于 pending（generate 被 mock 不会真正运行），活动任务禁止直接删除
    assert client.delete(f"/tasks/{tid}", headers=h).status_code == 400


def test_delete_terminal_task(client, db_session_factory):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    h = _auth(client)
    tid = client.post("/tasks", json={"idea": "x", "asset_ids": []}, headers=h).json()["task_id"]
    db = db_session_factory()
    task = db.get(GenerationTask, tid)
    task.status = TaskStatus.FAILED
    db.commit()
    db.close()
    assert client.delete(f"/tasks/{tid}", headers=h).status_code == 200
