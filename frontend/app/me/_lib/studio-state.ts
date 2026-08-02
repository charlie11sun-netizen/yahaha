export type Section = "overview" | "games" | "tasks" | "drafts" | "favorites" | "memory" | "settings";

export function isSection(value: string | null): value is Section {
  return value === "overview" || value === "games" || value === "tasks" || value === "drafts" || value === "favorites" || value === "memory" || value === "settings";
}
