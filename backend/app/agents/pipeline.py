"""Mock 5-Agent 生成流水线（USE_REAL_MODEL=false 时使用）。

保留与设计稿一致的 5 步与可读日志流；Packager 步骤执行真实的对象存储上传与
DB 写入，因此产物 bundle/manifest 真实落在 MinIO，Play 可远端加载。

接真实模型时，把 Coder 步骤替换为 LangGraph 节点调用 GPT-5.5 产出 HTML5，
其余步骤与本文件结构一致。
"""
import random
import time

from app.agents import bundles
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, Game, GameVersion, GenerationTask, Tag, User
from app.models.common import GameSource, GameStatus, StepStatus, TaskStatus, now_utc
from app.services.packaging import write_bundle

LOG_DELAY = 0.35

# (agent_key, 步骤名, 日志行)；{n} 会被替换为附件数量
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
        db.commit()

        n_assets = len(task.assets)
        game = None

        for i, (agent_key, step_name, logs) in enumerate(STEPS):
            step = AgentStep(
                task_id=task.id, seq=i + 1, agent=agent_key, name=step_name,
                status=StepStatus.RUNNING, started_at=now_utc(),
            )
            db.add(step)
            task.current_step = i + 1
            db.commit()

            for j, line in enumerate(logs):
                time.sleep(LOG_DELAY)
                db.add(AgentLog(step_id=step.id, seq=j, line=line.replace("{n}", str(n_assets))))
                task.tokens_used += random.randint(180, 420)
                db.commit()

            # Packager 步骤执行真实的产物上传与建库
            if agent_key == "packager":
                game = _package(db, task, user)

            step.status = StepStatus.DONE
            step.finished_at = now_utc()
            db.commit()

        task.result_game_id = game.id if game else None
        task.status = TaskStatus.SUCCEEDED
        task.finished_at = now_utc()
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 失败即落库，前端可读
        db.rollback()
        t = db.get(GenerationTask, task_id)
        if t:
            t.status = TaskStatus.FAILED
            t.error = str(exc)
            t.finished_at = now_utc()
            db.commit()
    finally:
        db.close()


def _package(db, task: GenerationTask, user: User | None) -> Game:
    meta = bundles.pick_bundle(task.idea)
    title = bundles.title_from(task.idea)
    # mock：选用已调好可玩性的模板。接真实 GPT-5.5 时，Coder 节点改用
    # app.agents.prompts.CODER_SYSTEM_PROMPT 约束产出（含同一套可玩性契约）。
    html = bundles.BUNDLES[meta["bundle"]]
    author_name = user.display_name if user else "PlayForge AI"

    game = Game(
        author_id=task.user_id,
        title=title,
        summary=(task.idea[:118] + "…") if len(task.idea) > 120 else task.idea,
        genre=meta["genre"],
        cover=meta["cover"],
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
        prompt=task.idea,
        plays_count=0,
        likes_count=0,
    )
    for name in meta["tags"] + ["AI"]:
        tag = db.query(Tag).filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
        game.tags.append(tag)
    db.add(game)
    db.flush()  # 取得 game.id

    info = write_bundle(game.id, "v1", html, title, author_name)
    db.add(GameVersion(
        game_id=game.id, version="v1", manifest_key=info["manifest_key"], bundle_key=info["bundle_key"],
        entry="index.html", runtime="iframe-sandbox", sha256=info["sha256"], size_bytes=info["size"],
        source_task_id=task.id,
    ))
    db.commit()
    return game
