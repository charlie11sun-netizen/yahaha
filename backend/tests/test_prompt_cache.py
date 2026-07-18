from types import SimpleNamespace

from app.agents import llm, planning_nodes, prompts, repair
from app.core.telemetry import bind_context, clear_context


def test_prompt_cache_key_is_stable_per_task_and_bounded(monkeypatch):
    monkeypatch.setattr(llm.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", "cache-test")

    bind_context(task_id="aaaaaaaa-1111-4222-8333-abcdefabcdef")
    try:
        first = llm.prompt_cache_key("planning-v1")
        assert first == llm.prompt_cache_key("planning-v1")
        assert first != llm.prompt_cache_key("author")
        long_key = llm.prompt_cache_key("planning-" + "x" * 200)
        assert long_key == llm.prompt_cache_key("planning-" + "x" * 200)
        assert len(long_key) <= 64
    finally:
        clear_context()

    bind_context(task_id="bbbbbbbb-1111-4222-8333-abcdefabcdef")
    try:
        assert llm.prompt_cache_key("planning-v1") != first
    finally:
        clear_context()

    shared = llm.prompt_cache_key("planning-v1", task_scoped=False)
    bind_context(task_id="cccccccc-1111-4222-8333-abcdefabcdef")
    try:
        assert llm.prompt_cache_key("planning-v1", task_scoped=False) == shared
    finally:
        clear_context()

    assert llm.prompt_cache_key("planning-v1") != llm.prompt_cache_key("planning-v1")
    monkeypatch.setattr(llm.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", " ")
    assert llm.prompt_cache_key("planning-v1") is None


def test_generation_planning_nodes_share_one_cacheable_prefix(monkeypatch):
    calls = []

    def fake_chat(system, user, **kwargs):
        calls.append((system, user, kwargs))
        if "IntentSpecAgent" in system:
            text = '{"title":"T","genre":"puzzle","theme":"clockwork"}'
        elif "GameplayPlanningAgent" in user:
            text = '{"expanded_brief":{},"mechanic_plan":{}}'
        else:
            text = "{}"
        return llm.LLMResult(
            text=text,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            model="gpt-5.6-sol",
            latency_ms=1,
            provider_response_id=f"resp-{len(calls)}",
        )

    monkeypatch.setattr(llm, "chat", fake_chat)
    base = {
        "use_real": True,
        "prompt": "make a clockwork logic puzzle",
        "normalized_prompt": "make a clockwork logic puzzle",
        "dimension": "2d",
        "asset_ids": [],
        "memory_context": "",
    }
    intent = planning_nodes.intent_spec_node(base)
    planned = planning_nodes.gameplay_planning_node({**base, **intent})
    design = planning_nodes.game_design_node({**base, **intent, **planned})
    replanned = repair.replan_game_design_node(
        {
            **base,
            **intent,
            **planned,
            **design,
            "last_error": "build failed",
            "replan_attempts": 0,
        }
    )

    assert len(prompts.PLANNING_SHARED_CACHE_PREFIX) >= 9000
    assert len(prompts.PLANNING_SHARED_CACHE_PREFIX.split()) >= 1300
    assert len(calls) == 4
    for system, _user, kwargs in calls:
        assert system.startswith(prompts.PLANNING_SHARED_CACHE_PREFIX)
        assert kwargs["cache_namespace"] == prompts.PLANNING_PROMPT_CACHE_NAMESPACE
        # Per-task cache bucket: the upstream never serves user content from
        # the shared global key, so every planning call must use the task key.
        assert kwargs["cache_task_scoped"] is True
        # The gateway strips store/previous_response_id, so no planning call
        # may rely on server-side conversation state ever again.
        assert "store" not in kwargs
        assert "previous_response_id" not in kwargs
        # Message-array input caps at the instructions head on this upstream;
        # the chain must stay string-form.
        assert "context_items" not in kwargs
    intent_call, plan_call, design_call, replan_call = calls

    # Standalone nodes keep the wrapped prompt + explicit cache prefix.
    assert intent_call[2]["cache_prefix"] == prompts.PLANNING_SHARED_CACHE_PREFIX
    assert replan_call[2]["cache_prefix"] == prompts.PLANNING_SHARED_CACHE_PREFIX

    # Chain members share one byte-identical instruction block (the bare
    # constitution) so the replayed transcript extends a stable prefix; their
    # role directives travel in the user turn instead.
    assert plan_call[0] == prompts.PLANNING_CHAIN_SYSTEM_PROMPT
    assert design_call[0] == prompts.PLANNING_CHAIN_SYSTEM_PROMPT
    assert "GameplayPlanningAgent" in plan_call[1]
    assert "GameDesignAgent" in design_call[1]
    assert "cache_prefix" not in plan_call[2]
    assert "cache_prefix" not in design_call[2]

    # Stage 3 extends stage 2's user string BYTE-FOR-BYTE (one growing string
    # is the only form the upstream prefix-caches) and records the lineage id.
    assert design_call[1].startswith(plan_call[1])
    assert "=== YOUR PREVIOUS REPLY ===" in design_call[1]
    assert "=== NEXT TASK ===" in design_call[1]
    assert design_call[2]["chained_from_response_id"] == "resp-2"
    # What the replayed reply already carries must not be re-serialized.
    assert "Playable brief" not in design_call[1]
    assert "Mechanic plan" not in design_call[1]

    # State handoff: the transcript stores per-turn contents (so the next
    # stage can rebuild the growing string without duplication), the lineage
    # id always points at the latest chain member, and a replan severs both.
    assert planned["planning_response_id"] == "resp-2"
    transcript = design["planning_transcript"]
    assert [item["role"] for item in transcript] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert transcript[0]["content"] == plan_call[1]
    assert transcript[2]["content"] != design_call[1]
    assert design_call[1].endswith(transcript[2]["content"])
    assert design["planning_response_id"] == "resp-3"
    assert replanned["planning_transcript"] is None
    assert replanned["planning_response_id"] is None


def test_explicit_cache_input_rejects_prefix_drift():
    try:
        llm._explicit_cache_input("node prompt", "user", "different prefix")
    except ValueError as exc:
        assert "exact cache_prefix" in str(exc)
    else:
        raise AssertionError("prefix drift must fail before sending an uncached request")


def test_chat_uses_key_only_implicit_cache_for_compatible_gateway(monkeypatch):
    captured = {}
    response = SimpleNamespace(
        model="gpt-5.6-sol",
        output=[],
        usage=SimpleNamespace(
            input_tokens=1800,
            output_tokens=5,
            total_tokens=1805,
            input_tokens_details=SimpleNamespace(
                cached_tokens=1536,
                cache_write_tokens=0,
            ),
        ),
    )

    class _Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(type="response.output_text.delta", delta="ready"),
                SimpleNamespace(type="response.completed", response=response),
            ]

    monkeypatch.setattr(
        llm,
        "_client",
        lambda timeout=None: SimpleNamespace(responses=_Responses()),
    )
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda _result, retried=False, previous_response_id=None: None,
    )
    monkeypatch.setattr(llm, "_record_stream_progress", lambda _line, payload=None: None)
    monkeypatch.setattr(llm.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", "cache-test")
    monkeypatch.setattr(llm.settings, "OPENAI_EXPLICIT_PROMPT_CACHE_ENABLED", False)

    bind_context(task_id="cccccccc-1111-4222-8333-abcdefabcdef")
    try:
        result = llm.chat(
            prompts.INTENT_SPEC_SYSTEM_PROMPT,
            "dynamic idea",
            model="gpt-5.6-sol",
            cache_namespace=prompts.PLANNING_PROMPT_CACHE_NAMESPACE,
            cache_prefix=prompts.PLANNING_SHARED_CACHE_PREFIX,
        )
    finally:
        clear_context()

    assert captured["instructions"] == prompts.INTENT_SPEC_SYSTEM_PROMPT
    assert captured["input"] == "dynamic idea"
    assert captured["prompt_cache_key"] == "cache-test:planning-v1:cccccccc1111"
    assert "prompt_cache_options" not in captured
    assert result.cached_tokens == 1536


def _streaming_responses(captured: dict, response: SimpleNamespace):
    class _Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(type="response.output_text.delta", delta="{}"),
                SimpleNamespace(type="response.completed", response=response),
            ]

    return SimpleNamespace(responses=_Responses())


def test_chat_replays_context_items_and_records_chain_lineage(monkeypatch):
    captured: dict = {}
    ledger: dict = {}
    progress: list = []
    response = SimpleNamespace(
        id="resp-design",
        model="gpt-5.6-sol",
        output=[],
        store=False,
        previous_response_id=None,
        usage=SimpleNamespace(
            input_tokens=9000,
            output_tokens=10,
            total_tokens=9010,
            input_tokens_details=SimpleNamespace(
                cached_tokens=8448, cache_write_tokens=0
            ),
        ),
    )
    monkeypatch.setattr(
        llm, "_client", lambda timeout=None: _streaming_responses(captured, response)
    )

    def fake_record(result, retried=False, previous_response_id=None):
        ledger["previous_response_id"] = previous_response_id
        ledger["provider_response_id"] = result.provider_response_id

    monkeypatch.setattr(llm, "_record_call", fake_record)
    monkeypatch.setattr(
        llm,
        "_record_stream_progress",
        lambda line, payload=None: progress.append((line, payload)),
    )

    transcript = [
        {"role": "user", "content": "plan the game"},
        {"role": "assistant", "content": '{"expanded_brief":{}}'},
    ]
    result = llm.chat(
        prompts.PLANNING_CHAIN_SYSTEM_PROMPT,
        "design the game",
        cache_namespace=prompts.PLANNING_PROMPT_CACHE_NAMESPACE,
        cache_task_scoped=False,
        context_items=transcript,
        chained_from_response_id="resp-plan",
    )

    # The transcript is replayed verbatim ahead of the new user turn, and no
    # server-side conversation state is requested from the stateless gateway.
    assert captured["input"] == [
        *transcript,
        {"role": "user", "content": "design the game"},
    ]
    assert captured["instructions"] == prompts.PLANNING_CHAIN_SYSTEM_PROMPT
    assert "previous_response_id" not in captured
    assert captured["store"] is False
    # Lineage lands in the ledger and in the usage log payload.
    assert ledger["previous_response_id"] == "resp-plan"
    assert ledger["provider_response_id"] == "resp-design"
    usage_payloads = [
        payload for _line, payload in progress if payload and payload.get("type") == "usage"
    ]
    assert usage_payloads
    assert usage_payloads[0]["previous_response_id"] == "resp-plan"
    assert usage_payloads[0]["context_messages"] == 2
    # Nothing was sent that the provider could drop, so no mismatch warning.
    assert not [
        payload
        for _line, payload in progress
        if payload and payload.get("type") == "chain_echo_mismatch"
    ]
    assert result.provider_response_id == "resp-design"


def test_chat_rejects_context_items_combined_with_server_side_chaining():
    try:
        llm.chat(
            "system",
            "user",
            context_items=[{"role": "user", "content": "x"}],
            previous_response_id="resp-1",
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError(
            "double-context request must fail before reaching the provider"
        )


def test_chat_warns_when_provider_drops_conversation_state(monkeypatch):
    captured: dict = {}
    progress: list = []
    response = SimpleNamespace(
        id="resp-b",
        model="gpt-5.6-sol",
        output=[],
        store=False,
        previous_response_id=None,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=1,
            total_tokens=101,
            input_tokens_details=SimpleNamespace(
                cached_tokens=0, cache_write_tokens=0
            ),
        ),
    )
    monkeypatch.setattr(
        llm, "_client", lambda timeout=None: _streaming_responses(captured, response)
    )
    monkeypatch.setattr(
        llm, "_record_call", lambda result, retried=False, previous_response_id=None: None
    )
    monkeypatch.setattr(
        llm,
        "_record_stream_progress",
        lambda line, payload=None: progress.append((line, payload)),
    )

    llm.chat("system", "user", previous_response_id="resp-a")

    assert captured["previous_response_id"] == "resp-a"
    assert captured["store"] is True
    warnings = [
        payload
        for _line, payload in progress
        if payload and payload.get("type") == "chain_echo_mismatch"
    ]
    assert warnings
    assert warnings[0]["sent_previous_response_id"] == "resp-a"
    assert warnings[0]["echoed_previous_response_id"] is None
    assert warnings[0]["sent_store"] is True
    assert warnings[0]["echoed_store"] is False
    assert any(
        "provider dropped conversation state" in line for line, _payload in progress
    )
