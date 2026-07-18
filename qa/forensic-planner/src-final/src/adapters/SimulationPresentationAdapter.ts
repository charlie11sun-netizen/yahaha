export type SimulationSignal<TSnapshot> = Readonly<{
  revision: number;
  changed: readonly string[];
  snapshot: TSnapshot;
}>;

/** Revision gate shared by scene wiring so presentation never rebuilds on unchanged frames. */
export class SimulationPresentationAdapter<TSnapshot> {
  private revision = -1;

  constructor(private readonly present: (snapshot: TSnapshot, changed: readonly string[]) => void) {}

  push(signal: SimulationSignal<TSnapshot>): boolean {
    if (signal.revision === this.revision) return false;
    this.revision = signal.revision;
    this.present(signal.snapshot, signal.changed);
    return true;
  }

  reset(): void { this.revision = -1; }
}
