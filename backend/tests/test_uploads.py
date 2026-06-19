def _auth(client):
    token = client.post(
        "/auth/register",
        json={"email": "u@u.com", "password": "secret1", "display_name": "U"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_ok(client):
    h = _auth(client)
    r = client.post("/uploads", files=[("files", ("a.png", b"x" * 100, "image/png"))], headers=h)
    assert r.status_code == 200
    assert r.json()["assets"][0]["name"] == "a.png"


def test_upload_bad_type(client):
    h = _auth(client)
    r = client.post("/uploads", files=[("files", ("a.exe", b"x", "application/x-msdownload"))], headers=h)
    assert r.status_code == 415


def test_upload_too_large(client):
    h = _auth(client)
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post("/uploads", files=[("files", ("big.png", big, "image/png"))], headers=h)
    assert r.status_code == 413
