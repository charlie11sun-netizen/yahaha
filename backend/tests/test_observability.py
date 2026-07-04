from decimal import Decimal
from types import SimpleNamespace


def _user():
    from app.models import User

    return User(
        email="obs@example.com",
        password_hash="x",
        display_name="Observer",
        avatar_initial="O",
    )


def test_llm_chat_records_usage_and_cost(db_session_factory, monkeypatch):
    from app.agents import llm
    from app.core.telemetry import bind_context, clear_context
    from app.models import AgentStep, GenerationTask, LLMCall
    from app.models.common import StepStatus

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="make a game")
    db.add(task)
    db.flush()
    step = AgentStep(
        task_id=task.id,
        seq=1,
        agent="GameDesignAgent",
        name="Game Design",
        status=StepStatus.RUNNING,
    )
    db.add(step)
    db.commit()
    db.close()

    class _FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                model="gpt-5.5",
                choices=[SimpleNamespace(message=SimpleNamespace(content=" playable plan "))],
                usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=2000, total_tokens=3000),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(llm, "SessionLocal", db_session_factory)
    monkeypatch.setattr(llm, "_client", lambda timeout=None: fake_client)

    bind_context(task_id=task.id, step_id=step.id)
    try:
        result = llm.chat("system", "user")
    finally:
        clear_context()

    text, tokens = result
    assert text == "playable plan"
    assert tokens == 3000
    assert result.prompt_tokens == 1000
    assert result.completion_tokens == 2000

    db = db_session_factory()
    call = db.query(LLMCall).one()
    refreshed_task = db.get(GenerationTask, task.id)
    assert call.task_id == task.id
    assert call.step_id == step.id
    assert call.total_tokens == 3000
    assert call.cost_usd == Decimal("0.021250")
    assert refreshed_task.cost_usd == Decimal("0.021250")
    db.close()


def test_tracing_tracks_attempts_tokens_and_failure_chain(db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.core.telemetry import clear_context
    from app.models import AgentStep, GenerationTask

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="make a game")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    monkeypatch.setattr(tracing, "SessionLocal", db_session_factory)

    failed_step_id = tracing.begin_step(task_id, "BuildValidateAgent", "Build Validation")
    tracing.finish_step(
        task_id,
        failed_step_id,
        ["validation failed"],
        tokens=123,
        failed=True,
    )
    repair_step_id = tracing.begin_step(task_id, "GameCodeAgentRepair", "Repair Code")
    second_repair_step_id = tracing.begin_step(task_id, "GameCodeAgentRepair", "Repair Code")

    db = db_session_factory()
    failed_step = db.get(AgentStep, failed_step_id)
    repair_step = db.get(AgentStep, repair_step_id)
    second_repair_step = db.get(AgentStep, second_repair_step_id)
    refreshed_task = db.get(GenerationTask, task_id)

    assert failed_step.tokens == 123
    assert refreshed_task.tokens_used == 123
    assert refreshed_task.failed_stage == "Build Validation"
    assert repair_step.attempt == 1
    assert repair_step.caused_by_step_id == failed_step_id
    assert second_repair_step.attempt == 2
    assert second_repair_step.caused_by_step_id == failed_step_id
    db.close()
    clear_context()
