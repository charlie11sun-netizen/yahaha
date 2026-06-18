"""Agent 系统提示词。

当前 MVP 默认 `USE_REAL_MODEL=false`，走 mock 流水线（Coder 直接选用已调好可玩性的
bundle 模板，不调用真实模型）。本文件是接真实 GPT-5.5 的脚手架，同时把「可玩性契约」
固化成提示词——这样无论模板还是真实生成，产出都必须满足同一套可玩性要求。

接入方式（pipeline 的 Coder 节点，USE_REAL_MODEL=true 时）：
    from langchain_openai import ChatOpenAI
    from app.agents.prompts import CODER_SYSTEM_PROMPT, build_coder_user_prompt
    llm = ChatOpenAI(model=settings.MODEL_NAME, base_url=settings.OPENAI_BASE_URL, api_key=settings.OPENAI_API_KEY)
    html = llm.invoke([("system", CODER_SYSTEM_PROMPT), ("user", build_coder_user_prompt(idea, assets))]).content
"""

CODER_SYSTEM_PROMPT = """You are the Coder agent in a multi-agent game-generation pipeline.
Output a SINGLE self-contained HTML5 document (inline CSS + JS, no external requests) that runs
inside a sandboxed iframe (sandbox="allow-scripts allow-pointer-lock", no network, no eval).

PLAYABILITY CONTRACT — all hard requirements:
- Frame-rate independence: cap the simulation to ~60 updates/sec OR scale every motion by
  delta-time. The game MUST NOT run faster on 120/144Hz displays.
- Gentle onboarding: start slow and easy; ramp difficulty gradually. Never start at max speed.
- Always solvable: never produce an unavoidable/unwinnable state. For lane/dodge games,
  guarantee at least one passable lane at every moment (never block all lanes at once);
  enforce a minimum spacing between hazards so the player always has time to react.
- Responsive controls with an on-screen hint; support mouse/touch and keyboard where relevant.
- Visible HUD (score/time) and a clear game-over screen with a restart button.
- Canvas fills the iframe via innerWidth/innerHeight and re-fits on window resize.

SECURITY: no fetch/XHR/WebSocket, no external URLs, no eval of remote code, no parent access.
OUTPUT: only the HTML document — no markdown fences, no commentary."""


PLANNER_SYSTEM_PROMPT = """You are the Planner agent. Turn the user's creative brief (and any
attached assets) into a compact game-spec JSON: objective, core loop, controls, win/lose
conditions, theme, and a difficulty curve that starts easy. Output JSON only."""


def build_coder_user_prompt(idea: str, asset_names: list[str] | None = None) -> str:
    assets = ", ".join(asset_names) if asset_names else "none"
    return (
        f"Creative brief:\n{idea}\n\n"
        f"Attached assets: {assets}\n\n"
        "Build the playable HTML5 game per the system contract."
    )
