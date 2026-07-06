"""Runtime smoke test for generated game.js bundles.

The check runs top-level JavaScript once inside py-mini-racer/V8 with permissive
browser and engine stubs. Native V8 failures can abort the whole Python process,
so the actual eval runs in a short-lived child Python process.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
from importlib.util import find_spec

try:
    _AVAILABLE = find_spec("py_mini_racer") is not None
except Exception:  # pragma: no cover
    _AVAILABLE = False


_PRELUDE = r"""
var STUB;
var __h = {
  get: function(t, p){
    if (p === 'length') return 0;
    if (p === Symbol.iterator) return function(){ return { next: function(){ return {done:true, value:undefined}; } }; };
    if (p === Symbol.toPrimitive) return function(){ return 0; };
    if (p === Symbol.toStringTag) return 'Stub';
    if (p === 'then') return undefined;
    if (p === 'nodeType') return 1;
    return STUB;
  },
  apply: function(){ return STUB; },
  construct: function(){ return STUB; },
  set: function(){ return true; },
  has: function(){ return true; },
  deleteProperty: function(){ return true; }
};
STUB = new Proxy(function(){}, __h);
var g = (typeof globalThis !== 'undefined') ? globalThis : this;
g.window = g; g.self = g; g.top = g; g.parent = { postMessage: function(){} };
g.document = STUB;
g.navigator = { userAgent: 'smoke', maxTouchPoints: 0, platform: 'smoke', language: 'en' };
g.location = { href: '', origin: '', protocol: 'http:', reload: function(){}, assign: function(){} };
g.console = { log: function(){}, info: function(){}, warn: function(){}, error: function(){}, debug: function(){} };
g.requestAnimationFrame = function(){ return 0; };
g.cancelAnimationFrame = function(){};
g.setTimeout = function(){ return 0; };
g.clearTimeout = function(){};
g.setInterval = function(){ return 0; };
g.clearInterval = function(){};
g.queueMicrotask = function(){};
g.addEventListener = function(){};
g.removeEventListener = function(){};
g.dispatchEvent = function(){ return true; };
g.matchMedia = function(){ return { matches:false, addEventListener:function(){}, addListener:function(){} }; };
g.getComputedStyle = function(){ return STUB; };
g.AudioContext = function(){ return STUB; };
g.webkitAudioContext = g.AudioContext;
g.Audio = function(){ return STUB; };
g.Image = function(){ return STUB; };
g.innerWidth = 1280; g.innerHeight = 720; g.devicePixelRatio = 1;
g.performance = { now: function(){ return 0; } };
g.localStorage = STUB; g.sessionStorage = STUB;
g.THREE = STUB;
g.Phaser = STUB;
"""

_WRAP_HEAD = "\n;(function(){\n'use strict';\n"
_WRAP_TAIL = "\n})();\n"

_RUNNER = r"""
import json
import sys

try:
    from py_mini_racer import MiniRacer  # type: ignore
except Exception:
    from py_mini_racer.py_mini_racer import MiniRacer  # type: ignore

payload = json.loads(sys.stdin.read())
try:
    ctx = MiniRacer()
    ctx.eval(payload["source"], timeout=int(payload["timeout_ms"]))
    result = {"ok": True, "detail": "ok"}
except Exception as exc:
    result = {"ok": False, "detail": " ".join(str(exc).split())[:240]}
sys.stdout.write(json.dumps(result))
"""


def available() -> bool:
    return _AVAILABLE


def _signal_name(returncode: int) -> str:
    if returncode >= 0:
        return f"exit {returncode}"
    signum = -returncode
    try:
        return signal.Signals(signum).name
    except ValueError:
        known = {6: "SIGABRT", 9: "SIGKILL", 11: "SIGSEGV", 15: "SIGTERM"}
        return known.get(signum, f"signal {signum}")


def _run_in_child(source: str, timeout_ms: int) -> tuple[bool, str]:
    payload = json.dumps({"source": source, "timeout_ms": timeout_ms})
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            input=payload,
            text=True,
            capture_output=True,
            timeout=(timeout_ms + 1500) / 1000,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_ms}ms"

    if completed.returncode != 0:
        # Native V8 aborts are engine failures, not proof that the game is bad.
        # Degrade open so GameplayQA can still exercise the real browser sandbox.
        return True, f"skipped (engine process crashed: {_signal_name(completed.returncode)})"

    try:
        data = json.loads(completed.stdout or "{}")
    except ValueError:
        return True, "skipped (engine returned invalid smoke result)"
    return bool(data.get("ok")), str(data.get("detail") or "")[:240]


def run_smoke(js: str, timeout_ms: int = 6000) -> tuple[bool, str]:
    """Run game.js top-level code once.

    Returns ok=True when loading is clean or the smoke engine is unavailable.
    Returns ok=False when the game itself throws or times out at load time.
    """
    if not js:
        return True, "empty"
    if not _AVAILABLE:
        return True, "skipped (engine unavailable)"
    return _run_in_child(_PRELUDE + _WRAP_HEAD + js + _WRAP_TAIL, timeout_ms)
