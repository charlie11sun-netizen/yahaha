from app.agents.pipeline import run_generation
from app.core.config import settings
from app.tasks.celery_app import celery


# Keep the task limit configurable. Real Phaser/code-generation streams can
# legitimately exceed 25 minutes, especially behind an OpenAI-compatible gateway.
@celery.task(
    name="generate_game",
    soft_time_limit=settings.GENERATION_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.GENERATION_TASK_TIME_LIMIT,
)
def generate_game(task_id: str) -> None:
    run_generation(task_id)
