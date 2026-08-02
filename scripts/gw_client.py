# -*- coding: utf-8 -*-
"""GameWeave UTF-8 generation client.

Creates a generation task with a (Chinese or any-language) prompt, polls it to
completion while streaming step transitions, then publishes the resulting game.

Usage:
  python scripts/gw_client.py --idea "制作一款..." [--dimension 2d] [--no-publish]
  python scripts/gw_client.py --idea-file prompt.txt
  python scripts/gw_client.py --watch <task_id>   # attach to an existing task
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
# The API's CSRF guard requires cookie-authenticated mutations to carry a
# trusted browser Origin header.
ORIGIN = "http://localhost:3000"
EMAIL = "demo@gameweave.dev"
PASSWORD = "password"
POLL_SECONDS = 15


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def login(session: requests.Session) -> None:
    resp = session.post(
        f"{BASE}/auth/session/login",
        data={"username": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    resp.raise_for_status()
    log(f"logged in as {EMAIL}")


def create_task(session: requests.Session, idea: str, dimension: str) -> str:
    payload = {"idea": idea, "dimension": dimension}
    resp = session.post(f"{BASE}/tasks", json=payload, timeout=30)
    resp.raise_for_status()
    task_id = resp.json()["task_id"]
    log(f"task created: {task_id}")
    return task_id


def poll(session: requests.Session, task_id: str) -> dict:
    last_key = None
    consecutive_errors = 0
    while True:
        try:
            resp = session.get(f"{BASE}/tasks/{task_id}", timeout=30)
            resp.raise_for_status()
            task = resp.json()
            consecutive_errors = 0
        except (requests.RequestException, ValueError) as exc:
            consecutive_errors += 1
            log(f"poll error ({consecutive_errors}/10): {exc}")
            if consecutive_errors >= 10:
                raise
            time.sleep(POLL_SECONDS)
            continue
        status = task.get("status")
        agent = task.get("current_agent") or "-"
        tokens = task.get("tokens_used") or 0
        key = (status, agent)
        if key != last_key:
            log(f"status={status} agent={agent} tokens={tokens}")
            last_key = key
        if status in {"succeeded", "failed", "cancelled"}:
            return task
        time.sleep(POLL_SECONDS)


def publish(session: requests.Session, game_id: str) -> dict:
    resp = session.post(f"{BASE}/games/{game_id}/publish", timeout=30)
    resp.raise_for_status()
    card = resp.json()
    log(f"published game {game_id}: {card.get('title')!r}")
    return card


def main() -> int:
    parser = argparse.ArgumentParser(description="GameWeave generation client")
    parser.add_argument("--idea", help="game idea prompt (UTF-8)")
    parser.add_argument("--idea-file", help="read the idea from a UTF-8 text file")
    parser.add_argument("--dimension", default="2d", choices=["2d", "3d"])
    parser.add_argument("--watch", help="poll an existing task id instead of creating")
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args()

    idea = args.idea
    if args.idea_file:
        with open(args.idea_file, encoding="utf-8") as fh:
            idea = fh.read().strip()
    if not args.watch and not idea:
        parser.error("--idea, --idea-file, or --watch is required")

    session = requests.Session()
    session.headers["Origin"] = ORIGIN
    login(session)

    task_id = args.watch or create_task(session, idea, args.dimension)
    task = poll(session, task_id)

    status = task.get("status")
    if status != "succeeded":
        log(f"task ended: {status} error={task.get('error')!r} failed_stage={task.get('failed_stage')!r}")
        print(json.dumps({"task_id": task_id, "status": status, "error": task.get("error")}, ensure_ascii=False))
        return 1

    game_id = (task.get("game") or {}).get("id") or task.get("result_game_id")
    log(f"task succeeded: game_id={game_id} tokens={task.get('tokens_used') or task.get('tokens')}")
    if game_id and not args.no_publish:
        publish(session, game_id)
    print(json.dumps({"task_id": task_id, "status": status, "game_id": game_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
