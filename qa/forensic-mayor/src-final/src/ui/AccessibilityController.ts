import Phaser from "phaser";
import { GameWeaveBridge } from "../systems/GameWeaveBridge";
import { Sfx } from "../systems/Sfx";
import type { CitySettings, InputBindings } from "../presentation/types";

export const DEFAULT_CITY_SETTINGS: Readonly<CitySettings> = Object.freeze({
  masterVolume: 0.8,
  musicVolume: 0.55,
  sfxVolume: 0.8,
  reducedMotion: false,
  highContrast: false,
});

export const DEFAULT_INPUT_BINDINGS: Readonly<InputBindings> = Object.freeze({
  pause: "Space",
  speed1: "Digit1",
  speed2: "Digit2",
  speed3: "Digit3",
  road: "KeyR",
  home: "KeyH",
  commercial: "KeyC",
  power: "KeyE",
  water: "KeyW",
  demolish: "KeyD",
  cancel: "Escape",
  overlay: "KeyP",
  confirm: "Enter",
});

interface PersistedPreferences {
  version: 1;
  settings: CitySettings;
  bindings: InputBindings;
}

const SLOT = "pixel-mayor.preferences.v1";
const VALID_CODES = /^(Space|Escape|Enter|Digit[0-9]|Key[A-Z]|Arrow(Up|Down|Left|Right))$/;
const clamp01 = (value: number, fallback: number): number =>
  Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : fallback;

export class AccessibilityController {
  private settingsValue: CitySettings = { ...DEFAULT_CITY_SETTINGS };
  private bindingsValue: InputBindings = { ...DEFAULT_INPUT_BINDINGS };
  private readonly listeners = new Set<(settings: Readonly<CitySettings>) => void>();

  constructor(private readonly scene?: Phaser.Scene) {
    this.applyRuntime();
  }

  get settings(): Readonly<CitySettings> { return this.settingsValue; }
  get bindings(): Readonly<InputBindings> { return this.bindingsValue; }

  async load(): Promise<void> {
    const fallback: PersistedPreferences = {
      version: 1,
      settings: { ...DEFAULT_CITY_SETTINGS },
      bindings: { ...DEFAULT_INPUT_BINDINGS },
    };
    const loaded = await GameWeaveBridge.load<PersistedPreferences>(SLOT, fallback);
    if (loaded?.version === 1) {
      this.settingsValue = this.sanitizeSettings(loaded.settings);
      this.bindingsValue = this.sanitizeBindings(loaded.bindings);
    }
    this.applyRuntime();
  }

  async save(): Promise<boolean> {
    return GameWeaveBridge.save(SLOT, {
      version: 1,
      settings: this.settingsValue,
      bindings: this.bindingsValue,
    } satisfies PersistedPreferences);
  }

  updateSettings(patch: Partial<CitySettings>, persist = true): Promise<boolean> {
    this.settingsValue = this.sanitizeSettings({ ...this.settingsValue, ...patch });
    this.applyRuntime();
    return persist ? this.save() : Promise.resolve(true);
  }

  rebind(action: keyof InputBindings, code: string, persist = true): Promise<boolean> {
    if (!VALID_CODES.test(code)) return Promise.resolve(false);
    this.bindingsValue = { ...this.bindingsValue, [action]: code };
    return persist ? this.save() : Promise.resolve(true);
  }

  reset(persist = true): Promise<boolean> {
    this.settingsValue = { ...DEFAULT_CITY_SETTINGS };
    this.bindingsValue = { ...DEFAULT_INPUT_BINDINGS };
    this.applyRuntime();
    return persist ? this.save() : Promise.resolve(true);
  }

  onChange(listener: (settings: Readonly<CitySettings>) => void): () => void {
    this.listeners.add(listener);
    listener(this.settingsValue);
    return () => this.listeners.delete(listener);
  }

  announce(message: string): void {
    this.scene?.events.emit("accessibility:announce", message);
    const canvas = this.scene?.game.canvas;
    if (canvas) canvas.setAttribute("aria-label", message);
  }

  private sanitizeSettings(value: Partial<CitySettings> | undefined): CitySettings {
    const source = value ?? {};
    return {
      masterVolume: clamp01(source.masterVolume ?? NaN, DEFAULT_CITY_SETTINGS.masterVolume),
      musicVolume: clamp01(source.musicVolume ?? NaN, DEFAULT_CITY_SETTINGS.musicVolume),
      sfxVolume: clamp01(source.sfxVolume ?? NaN, DEFAULT_CITY_SETTINGS.sfxVolume),
      reducedMotion: source.reducedMotion === true,
      highContrast: source.highContrast === true,
    };
  }

  private sanitizeBindings(value: Partial<InputBindings> | undefined): InputBindings {
    const source = value ?? {};
    const output = { ...DEFAULT_INPUT_BINDINGS } as InputBindings;
    for (const action of Object.keys(output) as Array<keyof InputBindings>) {
      const candidate = source[action];
      if (typeof candidate === "string" && VALID_CODES.test(candidate)) output[action] = candidate;
    }
    return output;
  }

  private applyRuntime(): void {
    Sfx.setMasterVolume(this.settingsValue.masterVolume * this.settingsValue.sfxVolume);
    const canvas = this.scene?.game.canvas;
    canvas?.classList.toggle("gw-high-contrast", this.settingsValue.highContrast);
    canvas?.classList.toggle("gw-reduced-motion", this.settingsValue.reducedMotion);
    for (const listener of this.listeners) listener(this.settingsValue);
  }
}
