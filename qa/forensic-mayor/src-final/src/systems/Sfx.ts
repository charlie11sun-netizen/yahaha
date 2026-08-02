/** Procedural WebAudio sound presets — no audio files, sandbox-safe.
 * Call Sfx.play("pickup" | "hit" | ...) on gameplay events; every key action
 * should be audible. playPitched() steps pitch up for combo chains. */
export type SfxName =
  | "pickup"
  | "hit"
  | "shoot"
  | "explosion"
  | "powerup"
  | "jump"
  | "select"
  | "win"
  | "lose";

interface TonePreset {
  wave: OscillatorType;
  from: number;
  to: number;
  duration: number;
  volume: number;
}

const PRESETS: Record<SfxName, TonePreset> = {
  pickup: { wave: "triangle", from: 660, to: 990, duration: 0.09, volume: 0.35 },
  hit: { wave: "square", from: 220, to: 90, duration: 0.14, volume: 0.4 },
  shoot: { wave: "square", from: 880, to: 320, duration: 0.08, volume: 0.25 },
  explosion: { wave: "sawtooth", from: 200, to: 32, duration: 0.42, volume: 0.5 },
  powerup: { wave: "triangle", from: 330, to: 880, duration: 0.28, volume: 0.4 },
  jump: { wave: "sine", from: 330, to: 590, duration: 0.12, volume: 0.3 },
  select: { wave: "sine", from: 520, to: 640, duration: 0.06, volume: 0.25 },
  win: { wave: "triangle", from: 440, to: 880, duration: 0.5, volume: 0.45 },
  lose: { wave: "sawtooth", from: 260, to: 70, duration: 0.6, volume: 0.4 },
};

export class Sfx {
  private static ctx: AudioContext | null = null;
  private static masterVolume = 1;

  /** Global 0..1 gain used by generated settings menus. */
  static setMasterVolume(value: number): number {
    const finite = Number.isFinite(value) ? value : 1;
    Sfx.masterVolume = Math.max(0, Math.min(1, finite));
    return Sfx.masterVolume;
  }

  static getMasterVolume(): number {
    return Sfx.masterVolume;
  }

  private static context(): AudioContext | null {
    if (typeof window === "undefined" || typeof window.AudioContext !== "function") return null;
    if (!Sfx.ctx) {
      try {
        Sfx.ctx = new window.AudioContext();
      } catch {
        return null;
      }
    }
    if (Sfx.ctx.state === "suspended") void Sfx.ctx.resume();
    return Sfx.ctx;
  }

  /** Play a named preset. Never throws — sound must not break gameplay. */
  static play(name: SfxName, volume = 1): void {
    Sfx.tone(PRESETS[name], 1, volume);
  }

  /** Same preset shifted by semitone steps — rising pitch sells combo chains. */
  static playPitched(name: SfxName, steps: number, volume = 1): void {
    Sfx.tone(PRESETS[name], Math.pow(2, steps / 12), volume);
  }

  private static tone(preset: TonePreset, multiplier: number, volume: number): void {
    try {
      const effectiveVolume = preset.volume * Math.max(0, volume) * Sfx.masterVolume;
      if (effectiveVolume <= 0) return;
      const ctx = Sfx.context();
      if (!ctx) return;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const now = ctx.currentTime;
      osc.type = preset.wave;
      osc.frequency.setValueAtTime(Math.max(1, preset.from * multiplier), now);
      osc.frequency.exponentialRampToValueAtTime(Math.max(1, preset.to * multiplier), now + preset.duration);
      gain.gain.setValueAtTime(Math.max(0.0001, effectiveVolume), now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + preset.duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + preset.duration + 0.02);
    } catch {
      /* sound must never break gameplay */
    }
  }
}
