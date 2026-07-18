import json


def test_generation_analysis_bundle_contains_full_stored_logs_and_cache_rollups(
    db_session_factory,
):
    from app.models import (
        AgentLog,
        AgentStep,
        AgentTraceEvent,
        GenerationTask,
        LLMCall,
        User,
    )
    from app.tools.export_generation_analysis import build_analysis_bundle

    db = db_session_factory()
    user = User(
        email="analysis-export@example.com",
        password_hash="x",
        display_name="Analysis Export",
        avatar_initial="A",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(
        user_id=user.id,
        idea="build a city",
        status="succeeded",
        spec_json=json.dumps({"title": "Small City"}),
        design_json=json.dumps({"systems": ["roads", "power"]}),
        contract_json=json.dumps({"meta": {"revision": 2}}),
        contract_hash="c" * 64,
        contract_revision=2,
        opik_trace_id="11111111-2222-4333-8444-555555555555",
    )
    db.add(task)
    db.flush()
    step = AgentStep(
        task_id=task.id,
        seq=1,
        agent="GameCodeAgent",
        name="Code Generation",
        status="done",
        tokens=120,
        decision_json=json.dumps({"runtime_consumed": True}),
    )
    db.add(step)
    db.flush()
    db.add(
        AgentLog(
            step_id=step.id,
            seq=0,
            line="cache measured",
            payload_json=json.dumps({"cached_tokens": 60}),
        )
    )
    db.add_all(
        [
            LLMCall(
                task_id=task.id,
                step_id=step.id,
                run_id="11111111-1111-4111-8111-111111111111",
                agent="GameCodeAgent",
                workflow_name="author",
                request_index=1,
                model="gpt-test",
                provider="openai",
                provider_route="gateway.test/v1",
                prompt_cache_key_hash="a" * 64,
                prompt_cache_namespace="author",
                prompt_cache_mode="routed_implicit",
                toolset_hash="b" * 64,
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                cached_tokens=60,
                cache_write_tokens=10,
                cache_read_reported=True,
                cache_write_reported=True,
                latency_ms=500,
            ),
            AgentTraceEvent(
                task_id=task.id,
                step_id=step.id,
                run_id="11111111-1111-4111-8111-111111111111",
                seq=1,
                source="agents_sdk",
                event_type="llm_input",
                agent="GameCodeAgent",
                payload_json=json.dumps(
                    {
                        "_trace_payload_truncated": True,
                        "original_chars": 2_000_000,
                        "json_preview": "{...",
                    }
                ),
                payload_chars=100,
            ),
        ]
    )
    db.commit()
    task_id = task.id

    bundle = build_analysis_bundle(db, task_id)

    assert bundle["schema_version"] == "gameweave.generation-analysis/1.0"
    assert bundle["task"]["idea"] == "build a city"
    assert bundle["task"]["design_contract"]["meta"]["revision"] == 2
    assert bundle["task"]["opik_trace_id"] == task.opik_trace_id
    assert bundle["steps"][0]["logs"][0]["payload"]["cached_tokens"] == 60
    assert bundle["llm_calls"][0]["prompt_cache_key_hash"] == "a" * 64
    assert bundle["cache_analysis"]["overall"]["weighted_cache_hit_rate"] == 0.6
    assert bundle["cache_analysis"]["overall"]["cache_write_rate"] == 0.25
    assert bundle["cache_analysis"]["by_request_index"][0]["request_index"] == "1"
    assert bundle["truncated_trace_event_count"] == 1
    assert bundle["trace_events"][0]["payload_truncated"] is True
    db.close()


def test_generation_analysis_bundle_can_exclude_large_trace_events(
    db_session_factory,
):
    from app.models import GenerationTask, User
    from app.tools.export_generation_analysis import build_analysis_bundle

    db = db_session_factory()
    user = User(
        email="analysis-light@example.com",
        password_hash="x",
        display_name="Analysis Light",
        avatar_initial="L",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="light export")
    db.add(task)
    db.commit()

    bundle = build_analysis_bundle(db, task.id, include_trace_events=False)

    assert bundle["trace_events_included"] is False
    assert bundle["trace_events"] == []
    assert bundle["trace_completeness"] == "trace events were excluded by request"
    db.close()
