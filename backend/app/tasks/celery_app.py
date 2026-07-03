from celery import Celery

from app.core.config import settings

celery = Celery(
    "gameweave",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.generate", "app.tasks.memory"],
)
celery.conf.update(
    task_acks_late=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    worker_max_memory_per_child=settings.WORKER_MAX_MEMORY_PER_CHILD,
    # acks_late 下 Redis broker 会在 visibility_timeout 后重投递"仍在跑"的任务。
    # 必须大于任务硬超时（generate.py time_limit=1800s），否则长任务会被第二个
    # worker 并发重跑：重复建 Game、重复 bundle、memory 证据重复计数。
    broker_transport_options={"visibility_timeout": 7200},
    beat_schedule={
        "purge-expired-memories-daily": {
            "task": "purge_expired_memories",
            "schedule": 24 * 60 * 60,
        },
    },
)
