from app.agents.pipeline import run_generation
from app.tasks.celery_app import celery


# 任务级 deadline：最坏路径 ~18 次 LLM 调用也必须在 25 分钟内收敛，超时走
# 失败路径（SoftTimeLimitExceeded 被 pipeline 捕获记为 FAILED），并保证任务
# 时长恒小于 broker visibility_timeout（celery_app.py），杜绝重投递双跑。
@celery.task(name="generate_game", soft_time_limit=1500, time_limit=1800)
def generate_game(task_id: str) -> None:
    run_generation(task_id)
