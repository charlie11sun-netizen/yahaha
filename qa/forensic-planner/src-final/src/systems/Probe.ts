import Phaser from "phaser";

/** Runtime behavior probes for automated QA.
 *
 * The QA sandbox reads `window.__GW_PROBES__.counts` after driving the game to
 * verify that declared content actually happens at runtime (scenes reached,
 * backdrops drawn, animations played, actors spawned, input processed).
 * Everything here is best-effort and bounded: a probe must never break or
 * slow the game.
 *
 * Scaffold systems report automatically (scene starts, animation playback,
 * Backdrop.draw, pointer processing, interactive registrations, key
 * registrations). Gameplay code adds the calls QA reconciles against the
 * design roster:
 * - `Probe.spawn("enemy", definition.id)` whenever an enemy or boss enters play
 * - `Probe.emit("projectile:spawn", projectileId)` when a projectile is fired
 */
interface ProbeStore {
  counts: Record<string, number>;
  total: number;
}

const MAX_KEYS = 300;
const MAX_DETAIL = 80;

function store(): ProbeStore | null {
  if (typeof window === "undefined") return null;
  const host = window as unknown as { __GW_PROBES__?: ProbeStore };
  if (!host.__GW_PROBES__) host.__GW_PROBES__ = { counts: {}, total: 0 };
  return host.__GW_PROBES__;
}

export const Probe = {
  /** Count a named runtime event, optionally qualified: emit("projectile:spawn", "bolt"). */
  emit(kind: string, detail = ""): void {
    try {
      const data = store();
      if (!data) return;
      const key = detail ? `${kind}|${String(detail).slice(0, MAX_DETAIL)}` : kind;
      if (data.counts[key] === undefined && Object.keys(data.counts).length >= MAX_KEYS) return;
      data.counts[key] = (data.counts[key] ?? 0) + 1;
      data.total += 1;
    } catch {
      /* probes must never break gameplay */
    }
  },

  /** Report an actor entering play, e.g. Probe.spawn("enemy", "grunt"). */
  spawn(category: string, id: string): void {
    Probe.emit(`spawn:${category}`, id);
  },
};

function resolvedKeyCode(key: unknown): number | undefined {
  if (typeof key === "number") return key;
  if (typeof key === "string") {
    const codes = Phaser.Input.Keyboard.KeyCodes as unknown as Record<string, number | undefined>;
    return codes[key.toUpperCase()];
  }
  if (key && typeof key === "object") return (key as { keyCode?: number }).keyCode;
  return undefined;
}

function install(): void {
  try {
    const host = window as unknown as { __GW_PROBE_HOOKS__?: boolean };
    if (host.__GW_PROBE_HOOKS__) return;
    host.__GW_PROBE_HOOKS__ = true;
    Probe.emit("probe:ready");

    const scenePrototype = Phaser.Scenes.ScenePlugin.prototype;
    const originalStart = scenePrototype.start;
    scenePrototype.start = function (this: Phaser.Scenes.ScenePlugin, key?: unknown, data?: object) {
      if (typeof key === "string" && key) Probe.emit("scene:start", key);
      return originalStart.call(this, key as never, data);
    };

    const animsPrototype = Phaser.Animations.AnimationState.prototype;
    const originalPlay = animsPrototype.play;
    animsPrototype.play = function (
      this: Phaser.Animations.AnimationState,
      key: unknown,
      ignoreIfPlaying?: boolean,
    ) {
      const name = typeof key === "string" ? key : ((key as { key?: string } | null)?.key ?? "");
      if (name) Probe.emit("anims:play", name);
      return originalPlay.call(this, key as never, ignoreIfPlaying);
    };

    // Raw input reaching the page at all (QA injects pointer/key events and
    // compares these against what the game actually processed).
    window.addEventListener("mousedown", () => Probe.emit("dom:down", "pointer"), { capture: true, passive: true });
    window.addEventListener("touchstart", () => Probe.emit("dom:down", "pointer"), { capture: true, passive: true });
    window.addEventListener("keydown", () => Probe.emit("dom:down", "key"), { capture: true, passive: true });

    // Pointer downs processed by scene input plugins. dom:down|pointer > 0
    // with input:down == 0 means the game's input pipeline is dead.
    const inputPrototype = Phaser.Input.InputPlugin.prototype as unknown as {
      processDownEvents: (pointer: Phaser.Input.Pointer) => number;
    };
    const originalProcessDown = inputPrototype.processDownEvents;
    inputPrototype.processDownEvents = function (
      this: { scene?: Phaser.Scene },
      pointer: Phaser.Input.Pointer,
    ): number {
      const sceneKey = this.scene && this.scene.scene ? this.scene.scene.key : "";
      Probe.emit("input:down", sceneKey);
      return originalProcessDown.call(this, pointer);
    };

    // Interactive registrations. A steady per-frame stream long after load
    // means UI is destroyed and rebuilt every tick — such buttons never enter
    // input hit-testing (they read as unclickable) and leak objects.
    const gameObjectPrototype = Phaser.GameObjects.GameObject.prototype as unknown as {
      setInteractive: (...args: unknown[]) => unknown;
    };
    const originalSetInteractive = gameObjectPrototype.setInteractive;
    gameObjectPrototype.setInteractive = function (this: unknown, ...args: unknown[]): unknown {
      Probe.emit("ui:interactive");
      return originalSetInteractive.apply(this, args);
    };

    // Dead key registrations: addKey resolving to no key code (for example
    // KeyCodes["2"] instead of KeyCodes.TWO) registers a key that never fires.
    const keyboardPrototype = Phaser.Input.Keyboard.KeyboardPlugin.prototype as unknown as {
      addKey: (key: unknown, enableCapture?: boolean, emitOnRepeat?: boolean) => Phaser.Input.Keyboard.Key;
    };
    const originalAddKey = keyboardPrototype.addKey;
    keyboardPrototype.addKey = function (
      this: unknown,
      key: unknown,
      enableCapture?: boolean,
      emitOnRepeat?: boolean,
    ): Phaser.Input.Keyboard.Key {
      const code = resolvedKeyCode(key);
      if (!code || Number.isNaN(code)) Probe.emit("key:invalid");
      return originalAddKey.call(this, key, enableCapture, emitOnRepeat);
    };

    // A 0x0 canvas after load means the game runs but renders invisible
    // (stylesheet race or broken scale wiring).
    window.addEventListener("load", () => {
      window.setTimeout(() => {
        try {
          const canvas = document.querySelector("canvas");
          if (canvas && canvas.getBoundingClientRect().width === 0) Probe.emit("canvas:zerosize");
        } catch {
          /* bounded */
        }
      }, 600);
    });
  } catch {
    /* instrumentation is best-effort */
  }
}

install();
