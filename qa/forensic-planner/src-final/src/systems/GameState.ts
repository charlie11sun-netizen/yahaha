export type GameStatus = "playing" | "won" | "lost";

export class GameState {
  score = 0;
  status: GameStatus = "playing";

  constructor(
    public lives: number,
    readonly targetScore: number,
  ) {}

  addScore(points: number): void {
    if (this.status !== "playing") return;
    this.score += points;
    if (this.score >= this.targetScore) this.status = "won";
  }

  loseLife(): void {
    if (this.status !== "playing") return;
    this.lives = Math.max(0, this.lives - 1);
    if (this.lives === 0) this.status = "lost";
  }
}
