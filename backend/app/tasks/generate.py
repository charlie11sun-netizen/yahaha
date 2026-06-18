from app.agents.pipeline import run_generation
from app.tasks.celery_app import celery


@celery.task(name="generate_game")
def generate_game(task_id: str) -> None:
    run_generation(task_id)
