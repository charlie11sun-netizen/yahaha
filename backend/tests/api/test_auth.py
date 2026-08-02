def _register(client, email="a@b.com", password="secret1", name="Ada"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


def test_register_and_me(client):
    r = _register(client)
    assert r.status_code == 200
    assert "token" not in r.json()
    cookie = r.headers["set-cookie"].lower()
    assert "gameweave_session=" in cookie
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["name"] == "Ada"


def test_duplicate_email_rejected(client):
    _register(client)
    assert _register(client).status_code == 409


def test_login_wrong_password(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "a@b.com", "password": "nope"})
    assert r.status_code == 401


def test_long_passwords_do_not_collide_after_bcrypt_limit(client):
    password = "a" * 72 + "first"
    _register(client, password=password)
    assert client.post(
        "/auth/login", json={"email": "a@b.com", "password": "a" * 72 + "second"}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "a@b.com", "password": password}
    ).status_code == 200


def test_oauth_demo_is_disabled_by_default(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_OAUTH_DEMO", False)
    assert client.post("/auth/oauth/google/demo").status_code == 404


def test_oauth_demo_requires_explicit_opt_in(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_OAUTH_DEMO", True)
    response = client.post("/auth/oauth/google/demo")
    assert response.status_code == 200
    assert response.json()["mock"] is True
    assert "token" not in response.json()
    assert "httponly" in response.headers["set-cookie"].lower()


def test_protected_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_change_password(client):
    _register(client)
    r = client.post(
        "/auth/change-password",
        json={"current_password": "secret1", "new_password": "secret2"},
    )
    assert r.status_code == 200
    assert client.post("/auth/login", json={"email": "a@b.com", "password": "secret2"}).status_code == 200
    assert client.post("/auth/login", json={"email": "a@b.com", "password": "secret1"}).status_code == 401


def test_update_profile(client):
    _register(client)
    r = client.patch("/auth/me", json={"display_name": "Ada L", "email": "ada@x.com"})
    assert r.status_code == 200
    assert r.json()["name"] == "Ada L"
    assert r.json()["email"] == "ada@x.com"


def test_delete_account(client):
    _register(client)
    response = client.delete("/auth/me")
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.get("/auth/me").status_code == 401


def test_fastapi_users_cookie_login_and_me(client):
    _register(client)
    client.cookies.clear()
    login = client.post(
        "/auth/session/login",
        data={"username": "a@b.com", "password": "secret1"},
    )
    assert login.status_code == 204
    assert "httponly" in login.headers["set-cookie"].lower()
    me = client.get("/auth/users/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "a@b.com"
    assert body["display_name"] == "Ada"
    assert body["is_active"] is True
    assert body["is_superuser"] is False
    assert body["is_verified"] is False


def test_bearer_header_is_not_an_authentication_transport(client):
    from app.core.security import create_access_token

    user_id = _register(client).json()["user"]["id"]
    token = create_access_token(user_id)
    client.cookies.clear()
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_cookie_authenticated_mutation_rejects_untrusted_origin(client):
    _register(client)
    untrusted = client.patch(
        "/auth/me",
        json={"display_name": "Mallory"},
        headers={"Origin": "https://evil.example"},
    )
    missing = client.patch(
        "/auth/me",
        json={"display_name": "Mallory"},
        headers={"Origin": ""},
    )
    assert untrusted.status_code == 403
    assert missing.status_code == 403
    assert untrusted.json()["detail"] == "CSRF_ORIGIN_MISMATCH"


def test_logout_clears_http_only_session_cookie(client):
    _register(client)
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.get("/auth/me").status_code == 401


def test_fastapi_users_register_reset_and_verify_routes(client):
    created = client.post(
        "/auth/users/register",
        json={"email": "native@x.com", "password": "secret1", "display_name": "Native"},
    )
    assert created.status_code == 201
    assert created.json()["display_name"] == "Native"

    forgot = client.post("/auth/users/forgot-password", json={"email": "native@x.com"})
    assert forgot.status_code == 202

    request_verify = client.post("/auth/users/request-verify-token", json={"email": "native@x.com"})
    assert request_verify.status_code == 202


def test_sync_user_database_crosses_threadpool_boundary(db_session_factory, monkeypatch):
    import asyncio

    from app.core import users as users_module
    from app.models import User

    db = db_session_factory()
    db.add(User(email="threaded@x.com", display_name="Threaded", avatar_initial="T"))
    db.commit()
    calls = []

    async def fake_threadpool(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(users_module, "run_in_threadpool", fake_threadpool)
    adapter = users_module.SyncSQLAlchemyUserDatabase(db)
    found = asyncio.run(adapter.get_by_email("threaded@x.com"))

    assert found is not None
    assert calls
    db.close()


def test_concurrent_signup_unique_race_maps_to_conflict(monkeypatch):
    import asyncio

    import pytest
    from fastapi_users import exceptions
    from sqlalchemy.exc import IntegrityError

    from app.core import users as users_module

    class RacingSession:
        rolled_back = False

        def add(self, _value):
            return None

        def commit(self):
            raise IntegrityError("insert", {}, RuntimeError("duplicate email"))

        def rollback(self):
            self.rolled_back = True

    async def fake_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    session = RacingSession()
    monkeypatch.setattr(users_module, "run_in_threadpool", fake_threadpool)
    adapter = users_module.SyncSQLAlchemyUserDatabase(session)

    with pytest.raises(exceptions.UserAlreadyExists):
        asyncio.run(adapter.create({"email": "race@x.com", "display_name": "Race"}))
    assert session.rolled_back is True
