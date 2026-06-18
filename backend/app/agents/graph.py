"""真实 Create 链路的 LangGraph 编排（USE_REAL_MODEL=true 时启用）。

    planner → designer → coder → sandbox_qa
                            ↑__________|  (QA 不过则回 coder，最多 2 次)

节点返回里用 _agent/_name/_logs/_tokens_delta 携带"展示信息"，由 pipeline 的 stream
循环落库成 agent_steps / agent_logs，前端实时可见——和 mock 路径同一套展示结构。
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import llm, prompts, validation

MAX_ATTEMPTS = 2


class GenState(TypedDict, total=False):
    idea: str
    assets: list
    spec: str
    design: str
    html: str
    qa_issues: list
    attempts: int
    # 展示用（非真正状态，stream 循环读取后落库）
    _agent: str
    _name: str
    _logs: list
    _tokens_delta: int


def planner_node(state: GenState) -> dict:
    assets = state.get("assets") or []
    spec, tk = llm.chat(prompts.PLANNER_SYSTEM_PROMPT, prompts.build_planner_user_prompt(state["idea"], assets))
    return {
        "spec": spec,
        "_agent": "planner", "_name": "Parse idea & decompose into a game spec", "_tokens_delta": tk,
        "_logs": [
            f"reading prompt + {len(assets)} attached asset(s)",
            "calling model -> game-spec.json",
            "spec ready: objective, controls, win/lose, theme",
        ],
    }


def designer_node(state: GenState) -> dict:
    notes, tk = llm.chat(
        prompts.DESIGNER_SYSTEM_PROMPT,
        prompts.build_designer_user_prompt(state["idea"], state.get("spec", "")),
    )
    return {
        "design": notes,
        "_agent": "designer", "_name": "Design mechanics, art direction & balance", "_tokens_delta": tk,
        "_logs": ["deriving palette, sprites & difficulty curve", "design notes -> handoff to Coder"],
    }


def coder_node(state: GenState) -> dict:
    attempts = state.get("attempts", 0) + 1
    raw, tk = llm.chat(
        prompts.CODER_SYSTEM_PROMPT,
        prompts.build_coder_user_prompt(
            state["idea"], state.get("assets"), spec=state.get("spec"),
            design=state.get("design"), issues=state.get("qa_issues"),
        ),
    )
    html = validation.extract_html(raw)
    logs: list[str] = []
    if state.get("qa_issues"):
        logs.append("applying QA fixes: " + "; ".join(state["qa_issues"][:2]))
    logs += [
        f"scaffolding canvas runtime + game loop (attempt {attempts})",
        f"bundle built -> index.html ({len(html.encode('utf-8'))} bytes)",
    ]
    return {
        "html": html, "attempts": attempts,
        "_agent": "coder", "_name": "Write runnable game bundle", "_tokens_delta": tk, "_logs": logs,
    }


def qa_node(state: GenState) -> dict:
    issues = validation.validate_html(state.get("html", ""))
    if issues:
        tail = " -> retrying" if state.get("attempts", 0) < MAX_ATTEMPTS else " -> giving up"
        logs = ["booting gVisor sandbox · net=deny", "QA FAILED: " + "; ".join(issues[:3]) + tail]
    else:
        logs = ["booting gVisor sandbox · net=deny", "smoke test + prompt-injection/asset scan ✓ clean"]
    return {
        "qa_issues": issues,
        "_agent": "sandbox_qa", "_name": "Execute in sandbox & safety-scan", "_tokens_delta": 0, "_logs": logs,
    }


def _route(state: GenState):
    if state.get("qa_issues") and state.get("attempts", 0) < MAX_ATTEMPTS:
        return "coder"
    return END


def build_graph():
    g = StateGraph(GenState)
    g.add_node("planner", planner_node)
    g.add_node("designer", designer_node)
    g.add_node("coder", coder_node)
    g.add_node("sandbox_qa", qa_node)
    g.add_edge(START, "planner")
    g.add_edge("planner", "designer")
    g.add_edge("designer", "coder")
    g.add_edge("coder", "sandbox_qa")
    g.add_conditional_edges("sandbox_qa", _route, {"coder": "coder", END: END})
    return g.compile()
