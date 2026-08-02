import Phaser from "phaser";
import { CityGameRuntime } from "../composition/CityGameRuntime";

/** CityGameScene owns only Phaser lifecycle; composition lives in CityGameRuntime. */
export class PlayScene extends Phaser.Scene {
  private runtime?: CityGameRuntime;

  constructor() { super("PlayScene"); }

  create(): void {
    this.runtime = new CityGameRuntime(this);
    this.runtime.create();
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.runtime?.destroy();
      this.runtime = undefined;
    });
  }

  update(_time: number, delta: number): void {
    this.runtime?.update(delta);
  }
}

export { PlayScene as CityGameScene };
