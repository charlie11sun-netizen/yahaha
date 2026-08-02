import Phaser from "phaser";
import { SimulationPresentationAdapter } from "../adapters/SimulationPresentationAdapter";

/** CityScene runtime kept on the scaffold's required PlayScene key. */
export class PlayScene extends Phaser.Scene {
  private adapter: SimulationPresentationAdapter | null = null;

  constructor() { super("PlayScene"); }

  create(): void {
    this.adapter = new SimulationPresentationAdapter(this);
    this.adapter.create();
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.adapter?.destroy();
      this.adapter = null;
    });
  }

  update(_time: number, delta: number): void {
    this.adapter?.update(delta);
  }
}

export { PlayScene as CityScene };
