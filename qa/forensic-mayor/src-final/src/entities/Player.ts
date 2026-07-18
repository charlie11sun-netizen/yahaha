import Phaser from "phaser";

export class Player extends Phaser.Physics.Arcade.Sprite {
  private readonly cursors: Phaser.Types.Input.Keyboard.CursorKeys;
  private readonly wasd: Record<"W" | "A" | "S" | "D", Phaser.Input.Keyboard.Key>;

  constructor(
    scene: Phaser.Scene,
    x: number,
    y: number,
    texture: string,
    private readonly moveSpeed: number,
  ) {
    super(scene, x, y, texture);
    scene.add.existing(this);
    scene.physics.add.existing(this);
    this.setCollideWorldBounds(true).setDepth(10);
    this.setDisplaySize(42, 42);
    this.cursors = scene.input.keyboard!.createCursorKeys();
    this.wasd = scene.input.keyboard!.addKeys("W,A,S,D") as Record<
      "W" | "A" | "S" | "D",
      Phaser.Input.Keyboard.Key
    >;
  }

  update(): void {
    const horizontal = Number(this.cursors.right.isDown || this.wasd.D.isDown)
      - Number(this.cursors.left.isDown || this.wasd.A.isDown);
    const vertical = Number(this.cursors.down.isDown || this.wasd.S.isDown)
      - Number(this.cursors.up.isDown || this.wasd.W.isDown);
    const direction = new Phaser.Math.Vector2(horizontal, vertical).normalize();
    this.setVelocity(direction.x * this.moveSpeed, direction.y * this.moveSpeed);
    if (direction.lengthSq() > 0) this.setRotation(direction.angle() + Math.PI / 2);
  }
}
