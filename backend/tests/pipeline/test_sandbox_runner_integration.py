import base64
import os
from pathlib import Path

import httpx
import pytest


SANDBOX_URL = os.environ.get("SANDBOX_URL", "").rstrip("/")
FIXTURES = Path(__file__).parents[1] / "fixtures" / "malicious_bundles"


def _bundle(name: str) -> list[dict]:
    root = FIXTURES / name
    return [
        {
            "path": path.name,
            "content_b64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
        for path in sorted(root.iterdir())
        if path.is_file()
    ]


@pytest.mark.skipif(not SANDBOX_URL, reason="SANDBOX_URL not set")
def test_malicious_bundles_are_blocked_and_runner_survives():
    client = httpx.Client(base_url=SANDBOX_URL, timeout=10)
    assert client.get("/health").json()["status"] == "ok"
    for name in ["dead_loop", "fetch_external", "memory_bomb", "page_error", "setinterval_storm", "zero_frame"]:
        response = client.post(
            "/run",
            json={"files": _bundle(name), "entry": "index.html", "timeout_ms": 1500, "simulate_input": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False, name
        assert client.get("/health").json()["status"] == "ok"
