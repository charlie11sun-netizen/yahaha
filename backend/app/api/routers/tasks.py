from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Asset, GenerationTask
from app.models.common import TaskStatus, now_utc
from app.schemas import TaskCreateIn
from app.services.serialize import task_out
from app.tasks.generate import generate_game

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _owned_task(task_id: str, user, db: Session) -> GenerationTask:
    task = db.get(GenerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your task")
    return task


@router.post("")
def create_task(body: TaskCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = GenerationTask(user_id=user.id, idea=body.idea, status=TaskStatus.PENDING)
    if body.asset_ids:
        task.assets = (
            db.query(Asset)
            .filter(Asset.id.in_(body.asset_ids), Asset.owner_id == user.id)
            .all()
        )
    db.add(task)
    db.commit()
    db.refresh(task)
    generate_game.delay(task.id)
    return {"task_id": task.id}


@router.get("")
def list_tasks(user=Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = (
        db.query(GenerationTask)
        .filter_by(user_id=user.id)
        .order_by(GenerationTask.created_at.desc())
        .all()
    )
    return {"items": [task_out(t) for t in tasks]}


@router.get("/{task_id}")
def get_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return task_out(_owned_task(task_id, user, db))


@router.post("/{task_id}/retry")
def retry_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _owned_task(task_id, user, db)
    if task.status != TaskStatus.FAILED:
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")
    for step in list(task.steps):
        db.delete(step)
    task.status = TaskStatus.PENDING
    task.error = None
    task.current_step = 0
    task.tokens_used = 0
    db.commit()
    generate_game.delay(task.id)
    return {"task_id": task.id}


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _owned_task(task_id, user, db)
    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="Only active tasks can be cancelled")
    task.status = TaskStatus.CANCELLED
    task.error = "Cancelled by user"
    task.finished_at = now_utc()
    db.commit()
    db.refresh(task)
    return task_out(task)
