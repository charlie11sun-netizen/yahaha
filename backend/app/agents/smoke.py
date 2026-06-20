"""生成产物的运行时冒烟测试 —— 在沙箱 V8 里把 game.js 顶层跑一遍。

QA 之前是纯静态扫描（grep 关键字），从不执行代码，所以 use-before-init / 读取
undefined 等"一加载就崩"的运行时错误会蒙混过关被发布。这里用 py_mini_racer
(内嵌 V8，无需系统 Node / 浏览器) 执行 game.js：

- requestAnimationFrame / setTimeout 设为 no-op，所以只跑加载期同步代码，不进游戏循环；
- 用一个"万能宽松桩"(Proxy) 顶替 document / window / THREE / Audio 等浏览器 & 引擎 API，
  任意取属性/调用/new/迭代都返回桩，绝不主动抛错；
- 这样游戏自身的真实 bug(读 undefined 的 .length、调用未定义函数、语法错误)才会抛，
  而正常的 DOM/THREE 调用不会误伤。

抛错即判定崩溃 → 调用方把它当作 QA 硬失败 → 触发现有 repair/replan 重生成。
引擎不可用(未安装)时"放行"(degrade open)，不阻断生成、不影响单测环境。
"""
from __future__ import annotations

try:  # py_mini_racer 的导出位置在不同版本略有差异
    from py_mini_racer import MiniRacer  # type: ignore
    _AVAILABLE = True
except Exception:  # pragma: no cover
    try:
        from py_mini_racer.py_mini_racer import MiniRacer  # type: ignore
        _AVAILABLE = True
    except Exception:
        MiniRacer = None  # type: ignore
        _AVAILABLE = False

# 万能宽松桩 + 浏览器/引擎全局。requestAnimationFrame 为 no-op：只测加载期同步代码。
_PRELUDE = r"""
var STUB;
var __h = {
  get: function(t, p){
    if (p === 'length') return 0;
    if (p === Symbol.iterator) return function(){ return { next: function(){ return {done:true, value:undefined}; } }; };
    if (p === Symbol.toPrimitive) return function(){ return 0; };
    if (p === Symbol.toStringTag) return 'Stub';
    if (p === 'then') return undefined;     // 不是 thenable，避免 await 卡住
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
"""

_WRAP_HEAD = "\n;(function(){\n'use strict';\n"
_WRAP_TAIL = "\n})();\n"


def available() -> bool:
    return _AVAILABLE


def run_smoke(js: str, timeout_ms: int = 6000) -> tuple[bool, str]:
    """执行一遍 game.js 顶层代码。

    返回 (ok, detail)。ok=True 表示加载期未抛错（或引擎不可用 → 放行）。
    ok=False 表示游戏一加载就崩，detail 为错误摘要。
    """
    if not js:
        return True, "empty"
    if not _AVAILABLE:
        return True, "skipped (engine unavailable)"
    try:
        ctx = MiniRacer()
        ctx.eval(_PRELUDE + _WRAP_HEAD + js + _WRAP_TAIL, timeout=timeout_ms)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 —— 任何引擎异常都视作"崩溃/失败"
        msg = " ".join(str(exc).split())
        return False, msg[:240]
