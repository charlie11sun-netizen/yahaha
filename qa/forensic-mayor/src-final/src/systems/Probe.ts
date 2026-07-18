import Phaser from "phaser";

/** Runtime behavior probes for automated QA.
 *
 * The QA sandbox reads `window.__GW_PROBES__.counts` after driving the game to
 * verify that declared content actually happens at runtime (scenes reached,
 * backdrops drawn, animations played, actors spawned). Everything here is
 * best-effort and bounded: a probe must never break or slow the game.
 *
 * Scaffold systems report automatically (scene starts, animation playback,
 * Backdrop.draw). Gameplay code adds the calls QA reconciles against the
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
  } catch {
    /* instrumentation is best-effort */
  }
}

install();
