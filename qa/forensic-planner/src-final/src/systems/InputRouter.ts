import Phaser from "phaser";

/** Pointer routing that keeps WORLD input (build/aim/select on the stage)
 * from firing underneath UI (HUD buttons, toolbars, panels, modals).
 *
 * Phaser delivers scene-level pointer events regardless of what was clicked:
 * a raw `scene.input.on("pointerdown", ...)` world handler ALSO fires when the
 * player presses a HUD button, placing/attacking/selecting behind the UI.
 * Register world handlers through `InputRouter.worldPointer` instead — they
 * are skipped whenever the pointer is over ANY interactive object, while a
 * drag that started on the stage keeps streaming to the world even if it
 * crosses UI mid-drag.
 *
 * Plain panels (non-interactive rectangles behind HUD text) do not block
 * clicks by themselves: call `InputRouter.shield(panel)` on every opaque UI
 * surface so presses on it stop reaching the world layer. */
export interface WorldPointerHandlers {
  down?(pointer: Phaser.Input.Pointer): void;
  move?(pointer: Phaser.Input.Pointer): void;
  up?(pointer: Phaser.Input.Pointer): void;
}

export const InputRouter = {
  /** Route stage-level pointer input, skipping presses that land on UI.
   * Returns a dispose function (also runs automatically on scene shutdown). */
  worldPointer(scene: Phaser.Scene, handlers: WorldPointerHandlers): () => void {
    let worldDrag = false;
    const onDown = (pointer: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]): void => {
      if (over.length > 0) return; // pointer is on UI — the world must not react
      worldDrag = true;
      handlers.down?.(pointer);
    };
    const onMove = (pointer: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]): void => {
      if (!worldDrag && over.length > 0) return;
      handlers.move?.(pointer);
    };
    const onUp = (pointer: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]): void => {
      const startedOnWorld = worldDrag;
      worldDrag = false;
      if (!startedOnWorld && over.length > 0) return;
      handlers.up?.(pointer);
    };
    scene.input.on("pointerdown", onDown);
    scene.input.on("pointermove", onMove);
    scene.input.on("pointerup", onUp);
    const dispose = (): void => {
      scene.input.off("pointerdown", onDown);
      scene.input.off("pointermove", onMove);
      scene.input.off("pointerup", onUp);
    };
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, dispose);
    return dispose;
  },

  /** Make a UI surface swallow pointer input so world handlers skip its area.
   * Call on every opaque panel/bar rectangle that is not itself a button.
   * (Containers need an explicit hit area — shield the background rectangle
   * inside them, not the container.) */
  shield<T extends Phaser.GameObjects.GameObject>(surface: T): T {
    if (!surface.input) surface.setInteractive();
    return surface;
  },
};
