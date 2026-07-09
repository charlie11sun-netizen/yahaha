export type Phase = "loading" | "ready" | "error";
export type RuntimeKey = "manifest" | "sandbox" | "bundle";
export type RuntimeStatus = "pending" | "running" | "ready" | "failed";

export const INITIAL_RUNTIME: Record<RuntimeKey, RuntimeStatus> = {
  manifest: "pending",
  sandbox: "pending",
  bundle: "pending",
};


export function runtimeLabel(status: RuntimeStatus) {
  if (status === "ready") return "Ready";
  if (status === "running") return "Running";
  if (status === "failed") return "Failed";
  return "Pending";
}

export function coverBg(cover?: string | null) {
  if (cover && (cover.startsWith("/") || cover.startsWith("http"))) return `url("${cover}") center / cover`;
  return cover || "linear-gradient(135deg,#101844,#4f7dff)";
}
