from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.db.session import get_db
from app.schemas import OkOut, TaskIdOut, TaskListOut, TaskOut, TaskRetryOut, TaskCreateIn, TaskRevisionIn
from app.services import task_actions
from app.services.errors import ServiceError
from app.services.serialize import task_out
from app.tasks.generate import generate_game

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _run(action):
    try:
        return action()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "",
    response_model=TaskIdOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(20, 3600, "task_create"))],
)
def create_task(body: TaskCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _run(lambda: task_actions.create_task(db, body, user, queue=generate_game))
    return {"task_id": task.id}


@router.get("", response_model=TaskListOut, response_model_exclude_unset=True)
def list_tasks(user=Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = task_actions.list_tasks(db, user)
    return {"items": [task_out(task, include_details=False) for task in tasks]}


@router.get("/{task_id}", response_model=TaskOut, response_model_exclude_unset=True)
def get_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _run(lambda: task_actions.get_task(db, task_id, user))
    return task_out(task)


@router.post(
    "/{task_id}/revise",
    response_model=TaskIdOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(20, 3600, "task_revise"))],
)
def revise_task(
    task_id: str,
    body: TaskRevisionIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revision = _run(lambda: task_actions.revise_task(db, task_id, body, user, queue=generate_game))
    return {"task_id": revision.id}


@router.post("/{task_id}/retry", response_model=TaskRetryOut, response_model_exclude_unset=True)
def retry_task(
    task_id: str,
    from_scratch: bool = False,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task, mode = _run(
        lambda: task_actions.retry_task(
            db,
            task_id,
            user,
            from_scratch=from_scratch,
            queue=generate_game,
        )
    )
    return {"task_id": task.id, "mode": mode}


@router.post("/{task_id}/cancel", response_model=TaskOut, response_model_exclude_unset=True)
def cancel_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _run(lambda: task_actions.cancel_task(db, task_id, user))
    return task_out(task)


@router.delete("/{task_id}", response_model=OkOut, response_model_exclude_unset=True)
def delete_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _run(lambda: task_actions.delete_task(db, task_id, user))
    return {"ok": True}
