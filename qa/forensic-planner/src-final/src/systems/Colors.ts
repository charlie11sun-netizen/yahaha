/** Convert a "#rrggbb" palette string to the numeric color Phaser APIs expect. */
export function colorNum(hex: string): number {
  const clean = hex.trim().replace("#", "");
  const expanded = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const value = Number.parseInt(expanded, 16);
  return Number.isFinite(value) ? value : 0xffffff;
}
