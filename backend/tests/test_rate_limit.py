import pytest
from fastapi import HTTPException

from app.api import deps


class _CountingRedis:
    def __init__(self):
        self.n = 0

    def incr(self, key):
        self.n += 1
        return self.n

    def expire(self, key, window):
        return True


class _Req:
    class client:
        host = "1.2.3.4"


def test_rate_limit_raises_after_limit(monkeypatch):
    shared = _CountingRedis()
    monkeypatch.setattr(deps, "_get_rl_redis", lambda: shared)
    dep = deps.rate_limit(limit=3, window=60, scope="unit")
    for _ in range(3):
        dep(_Req())
    with pytest.raises(HTTPException) as exc:
        dep(_Req())
    assert exc.value.status_code == 429


def test_rate_limit_fails_closed_when_redis_down(monkeypatch):
    import redis as redis_lib

    def boom():
        raise redis_lib.RedisError("down")

    monkeypatch.setattr(deps, "_get_rl_redis", boom)
    dep = deps.rate_limit(limit=1, window=60, scope="unit2")
    with pytest.raises(HTTPException) as exc:
        dep(_Req())
    assert exc.value.status_code == 503
    assert exc.value.detail == "RATE_LIMIT_UNAVAILABLE"


def test_rate_limit_can_fail_open_when_explicitly_configured(monkeypatch):
    import redis as redis_lib
    from app.core.config import settings

    def boom():
        raise redis_lib.RedisError("down")

    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)
    monkeypatch.setattr(deps, "_get_rl_redis", boom)
    dep = deps.rate_limit(limit=1, window=60, scope="unit3")
    dep(_Req())
