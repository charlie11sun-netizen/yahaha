from urllib.parse import parse_qs, urlparse

import jwt


def test_oauth_start_binds_expiring_state_to_browser_cookie(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    response = client.get("/auth/oauth/google/start", follow_redirects=False)
    assert response.status_code in (302, 307)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    claims = jwt.decode(state, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert claims["p"] == "google"
    assert claims["n"]
    assert "exp" in claims
    assert "gameweave_oauth_state=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_oauth_callback_rejects_state_without_bound_cookie(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    start = client.get("/auth/oauth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    client.cookies.clear()
    response = client.get(
        "/auth/oauth/google/callback",
        params={"code": "unused", "state": state},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid OAuth state"
