"""生成流水线：mock（默认，离线）与 real（LangGraph + GPT-5.5）两条路径。

两条路径共用 agent_steps / agent_logs 的实时流式落库，前端一致地展示步骤与日志。
USE_REAL_MODEL=true 且配置了 OPENAI_API_KEY 时走真实链路，否则走 mock。
"""
import json
import random
import re
import time

from app.agents import bundles
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, Game, GameVersion, GenerationTask, Tag, User
from app.models.common import GameSource, GameStatus, StepStatus, TaskStatus, now_utc
from app.services.packaging import write_bundle

LOG_DELAY = 0.35

# mock 流水线步骤：(agent_key, 步骤名, 日志行)；{n} 替换为附件数量
STEPS = [
    ("planner", "Parse idea & decompose into a game spec", [
        "reading prompt + {n} attached asset(s)",
        "classified prototype -> reaction / collection loop",
        "emitted game-spec.json (objective, controls, win/lose, theme)",
    ]),
    ("designer", "Design mechanics, art direction & balance", [
        "palette locked: warm / arcade · 4 sprites",
        "tuned spawn-rate curve & 30s round timer",
        "wrote design-doc.md -> handoff to Coder",
    ]),
    ("coder", "Write runnable game bundle", [
        "scaffolding canvas runtime + input layer",
        "implemented loop, scoring, collision, game-over",
        "bundle built -> index.html",
    ]),
    ("sandbox_qa", "Execute in sandbox & safety-scan", [
        "booting gVisor sandbox · cpu=1 mem=256MB net=deny",
        "smoke test: 600 frames @60fps, 0 errors",
        "prompt-injection & asset scan ✓ clean",
    ]),
    ("packager", "Upload to object storage & write meta", [
        "PUT index.html -> object storage",
        "PUT manifest.json · sha256 stamped",
        "INSERT games row -> status=preview ✓",
    ]),
]


def run_generation(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return
        user = db.get(User, task.user_id)
        task.status = TaskStatus.RUNNING
        task.started_at = now_utc()
        task.current_step = 0
        task.tokens_used = 0
        task.error = None
        db.commit()

        use_real = settings.USE_REAL_MODEL and bool(settings.OPENAI_API_KEY.strip())
        game = run_real(db, task, user) if use_real else run_mock(db, task, user)

        task.result_game_id = game.id if game else None
        task.status = TaskStatus.SUCCEEDED
        task.finished_at = now_utc()
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 失败即落库，前端可读
        db.rollback()
        t = db.get(GenerationTask, task_id)
        if t:
            t.status = TaskStatus.FAILED
            t.error = str(exc)[:500]
            t.finished_at = now_utc()
            db.commit()
    finally:
        db.close()


# ---------------- mock 路径 ----------------
def run_mock(db, task: GenerationTask, user: User | None) -> Game:
    n_assets = len(task.assets)
    game = None
    for i, (agent_key, step_name, logs) in enumerate(STEPS):
        step = AgentStep(task_id=task.id, seq=i + 1, agent=agent_key, name=step_name,
                         status=StepStatus.RUNNING, started_at=now_utc())
        db.add(step)
        task.current_step = i + 1
        db.commit()
        for j, line in enumerate(logs):
            time.sleep(LOG_DELAY)
            db.add(AgentLog(step_id=step.id, seq=j, line=line.replace("{n}", str(n_assets))))
            task.tokens_used += random.randint(180, 420)
            db.commit()
        if agent_key == "packager":
            meta = bundles.pick_bundle(task.idea)
            title = bundles.title_from(task.idea)
            html = bundles.BUNDLES[meta["bundle"]]
            summary = (task.idea[:118] + "…") if len(task.idea) > 120 else task.idea
            game, _ = _persist_game(db, task, user, html, title, meta["genre"], meta["cover"],
                                    summary, meta["tags"] + ["AI"])
        step.status = StepStatus.DONE
        step.finished_at = now_utc()
        db.commit()
    return game


# ---------------- real 路径（LangGraph + GPT-5.5）----------------
def run_real(db, task: GenerationTask, user: User | None) -> Game:
    from app.agents import validation  # 延迟导入
    from app.agents.graph import build_graph

    graph = build_graph()
    initial = {"idea": task.idea, "assets": [a.filename for a in task.assets], "attempts": 0}

    step_seq = 0
    total_tokens = 0
    final: dict = {}
    for event in graph.stream(initial, stream_mode="updates"):
        for node_name, update in event.items():
            if not isinstance(update, dict):
                continue
            final.update({k: v for k, v in update.items() if not k.startswith("_")})
            step_seq += 1
            step = AgentStep(task_id=task.id, seq=step_seq,
                             agent=update.get("_agent", node_name), name=update.get("_name", node_name),
                             status=StepStatus.RUNNING, started_at=now_utc())
            db.add(step)
            task.current_step = step_seq
            db.commit()
            for i, line in enumerate(update.get("_logs", [])):
                db.add(AgentLog(step_id=step.id, seq=i, line=str(line)))
            total_tokens += int(update.get("_tokens_delta", 0) or 0)
            task.tokens_used = total_tokens
            db.commit()
            step.status = StepStatus.DONE
            step.finished_at = now_utc()
            db.commit()

    html = final.get("html", "")
    issues = validation.validate_html(html)
    if issues:
        raise RuntimeError("generation failed QA after retries: " + "; ".join(issues[:3]))

    # Packager（产物上传 + 建库）
    step_seq += 1
    pstep = AgentStep(task_id=task.id, seq=step_seq, agent="packager",
                      name="Upload to object storage & write meta", status=StepStatus.RUNNING, started_at=now_utc())
    db.add(pstep)
    task.current_step = step_seq
    db.commit()

    meta = _spec_meta(final, task.idea)
    db.add(AgentLog(step_id=pstep.id, seq=0, line="PUT index.html -> object storage"))
    db.commit()
    game, info = _persist_game(db, task, user, html, meta["title"], meta["genre"], meta["cover"],
                               meta["summary"], meta["tags"])
    db.add(AgentLog(step_id=pstep.id, seq=1, line="PUT manifest.json · sha256 " + info["sha256"][:12]))
    db.add(AgentLog(step_id=pstep.id, seq=2, line="INSERT games row -> status=preview ✓"))
    pstep.status = StepStatus.DONE
    pstep.finished_at = now_utc()
    db.commit()
    return game


def _spec_meta(state: dict, idea: str) -> dict:
    """从 Planner 的 game-spec JSON 取展示元信息，缺失则回退到启发式。"""
    data: dict = {}
    m = re.search(r"\{.*\}", state.get("spec", "") or "", re.S)
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:
            data = {}
    fb = bundles.pick_bundle(idea)
    title = (str(data.get("title") or "").strip() or bundles.title_from(idea))[:60] or "Untitled Game"
    genre = (str(data.get("genre") or "").strip() or fb["genre"])[:80]
    cover = data.get("cover")
    if not (isinstance(cover, str) and cover.startswith("linear-gradient")):
        cover = fb["cover"]
    tags = data.get("tags")
    if not (isinstance(tags, list) and tags):
        tags = fb["tags"]
    tags = [str(t)[:30] for t in tags][:4] + ["AI"]
    summary = str(data.get("summary") or "").strip() or ((idea[:118] + "…") if len(idea) > 120 else idea)
    return {"title": title, "genre": genre, "cover": cover, "tags": tags, "summary": summary[:200]}


def _persist_game(db, task, user, html, title, genre, cover, summary, tags) -> tuple[Game, dict]:
    game = Game(author_id=task.user_id, title=title, summary=summary, genre=genre, cover=cover,
                source=GameSource.CREATE, status=GameStatus.PREVIEW, current_version="v1",
                prompt=task.idea, plays_count=0, likes_count=0)
    for name in tags:
        tag = db.query(Tag).filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
        game.tags.append(tag)
    db.add(game)
    db.flush()
    info = write_bundle(game.id, "v1", html, title, user.display_name if user else "PlayForge AI")
    db.add(GameVersion(
        game_id=game.id, version="v1", manifest_key=info["manifest_key"], bundle_key=info["bundle_key"],
        entry="index.html", runtime="iframe-sandbox", sha256=info["sha256"], size_bytes=info["size"],
        source_task_id=task.id,
    ))
    db.commit()
    return game, info
