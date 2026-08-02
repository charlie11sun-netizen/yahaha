---
name: gameweave-runtime
description: "GameWeave sandbox runtime contract for generated game bundles: file whitelist, forbidden APIs, CSP, score reporting, smoke-test constraints. Read this before fixing validation failures about forbidden APIs, external URLs, or load-time crashes."
---

# GameWeave Runtime Contract

Every generated game runs inside a sandboxed iframe (`sandbox="allow-scripts allow-pointer-lock"`)
behind a strict CSP: `default-src 'none'`, `connect-src 'none'` (no network at all), assets only
from same-origin / `data:` / `blob:`.

## Bundle rules (enforced by build validation)

- Exactly these files: `index.html`, `style.css`, `game.js`. Each ≤ 400KB.
- `index.html` must reference `game.js` via a relative `<script src="game.js"></script>`.
- 3D games additionally load the self-hosted engine with `<script src="three.min.js"></script>`
  BEFORE `game.js` and use the global `THREE`. Never load engines from a CDN.
- Forbidden anywhere in the bundle (regex-scanned): `eval()`, `new Function`, `fetch()`,
  `XMLHttpRequest`, `WebSocket`, `EventSource`, `navigator.sendBeacon`, dynamic `import()`,
  `localStorage`, `sessionStorage`, `document.cookie`, `window.parent` / `window.top` access
  (the postMessage call below is the only exception), `<script src="http...">`, and any
  external `http(s)://` URL (w3.org namespace URIs are the only exemption).

## Allowed patterns

- All graphics procedural (canvas / WebGL drawing) or inline `data:` / `blob:` URIs.
- Sound via WebAudio oscillators or `data:` URIs — no external audio files.
- Report score: `window.parent.postMessage({ type: "gameweave:score", points: <integer>, name: <optional string> }, "*")`.
- Restart must work without reloading the page (rebind state, don't call `location.reload()`).

## Smoke test

`game.js` top-level code runs once in a stubbed V8 (no real DOM; `document`/`window`/`THREE`
are permissive stubs; `requestAnimationFrame`/`setTimeout` are no-ops). It must not throw at
load time. Typical crashes to avoid:

- use-before-init (`const` read in an earlier function call), reading properties of `undefined`
  at top level, syntax errors;
- work that needs a real canvas should happen inside functions first invoked by
  `requestAnimationFrame` or input handlers, not at top level.
