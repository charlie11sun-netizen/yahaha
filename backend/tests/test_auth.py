def _register(client, email="a@b.com", password="secret1", name="Ada"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


def test_register_and_me(client):
    r = _register(client)
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["name"] == "Ada"


def test_duplicate_email_rejected(client):
    _register(client)
    assert _register(client).status_code == 409


def test_login_wrong_password(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "a@b.com", "password": "nope"})
    assert r.status_code == 401


def test_protected_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_change_password(client):
    token = _register(client).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/auth/change-password",
        json={"current_password": "secret1", "new_password": "secret2"},
        headers=h,
    )
    assert r.status_code == 200
    assert client.post("/auth/login", json={"email": "a@b.com", "password": "secret2"}).status_code == 200
    assert client.post("/auth/login", json={"email": "a@b.com", "password": "secret1"}).status_code == 401


def test_update_profile(client):
    token = _register(client).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.patch("/auth/me", json={"display_name": "Ada L", "email": "ada@x.com"}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Ada L"
    assert r.json()["email"] == "ada@x.com"


def test_delete_account(client):
    token = _register(client).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.delete("/auth/me", headers=h).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 401
