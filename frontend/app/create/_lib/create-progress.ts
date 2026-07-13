import type { StepSummary, Task, UploadedAsset } from "@/lib/types";
import { cleanStreamLine, isStreamTokenLine, visibleAgentLogs } from "./agent-activity";
import { formatRelative } from "./create-time";

export const GAMEPLAY_STEP_KEYS = ["gameplay_qa", "gameplay_repair"] as const;
export type UserStep = { key: string; label: string; backendKeys?: readonly string[]; optional?: boolean };

const USER_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Idea checked" },
  {
    key: "intent_spec",
    label: "Game spec created",
    backendKeys: ["intent_spec", "gameplay_planning", "brief_expansion", "mechanic_planner", "archetype_router"],
  },
  { key: "asset_processing", label: "Assets processed" },
  { key: "game_design", label: "Game designed", backendKeys: ["game_design", "content_plan", "balance_plan"] },
  { key: "code_generation", label: "Files generated" },
  { key: "build_validation", label: "Validating build", backendKeys: ["build_validation", "static_validation"] },
  { key: "gameplay_qa", label: "Playtesting game", backendKeys: GAMEPLAY_STEP_KEYS, optional: true },
  { key: "publish_artifact", label: "Preparing preview" },
  { key: "ready", label: "Ready to publish" },
];
const USER_REVISION_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Feedback checked" },
  { key: "feedback_understanding", label: "Feedback understood" },
  { key: "code_revision", label: "Existing files revised" },
  { key: "build_validation", label: "Validating changes" },
  { key: "gameplay_qa", label: "Regression playtest" },
  { key: "publish_revision", label: "Saving new preview" },
  { key: "ready", label: "Ready to publish" },
];
const USER_REMIX_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Remix checked" },
  { key: "feedback_understanding", label: "Remix goal understood" },
  { key: "code_revision", label: "Source files transformed" },
  { key: "build_validation", label: "Validating remix" },
  { key: "gameplay_qa", label: "Playtesting remix" },
  { key: "publish_remix", label: "Saving remix preview" },
  { key: "ready", label: "Ready to publish" },
];

export type StepState = "pending" | "running" | "completed" | "failed";
export type StepRow = { key: string; label: string; status: StepState; summary?: string | null };

export function buildStepRows(task?: Task): StepRow[] {
  const backend = new Map<string, StepSummary>((task?.step_summaries ?? []).map((step) => [step.step, step]));
  const configuredSteps =
    task?.task_kind === "remix" ? USER_REMIX_STEPS : task?.task_kind === "revision" ? USER_REVISION_STEPS : USER_STEPS;
  const visibleSteps = configuredSteps.filter((step) => !step.optional || stepHasBackendSummary(step, backend));
  const rows = visibleSteps.map((step) => {
    if (step.key === "ready") {
      return {
        key: step.key,
        label: step.label,
        status: task?.status === "succeeded" ? "completed" : "pending",
      } satisfies StepRow;
    }
    const summaries = stepSummariesFor(step, backend);
    return {
      key: step.key,
      label: step.label,
      status: mergedStepStatus(summaries),
      summary: displayStepSummary(summaries),
    } satisfies StepRow;
  });

  if (task?.status === "succeeded") {
    return rows.map((row) => ({ ...row, status: "completed" }));
  }

  if (task?.status === "failed" || task?.status === "cancelled") {
    const failedIndex = rows.findIndex((row) => row.status === "running" || row.status === "failed");
    const index = failedIndex >= 0 ? failedIndex : Math.min(Math.max((task.current_step || 1) - 1, 0), rows.length - 1);
    return rows.map((row, rowIndex) => (rowIndex === index ? { ...row, status: "failed" } : row));
  }

  return rows;
}

function stepKeys(step: UserStep) {
  return step.backendKeys ?? [step.key];
}

function stepSummariesFor(step: UserStep, backend: Map<string, StepSummary>) {
  return stepKeys(step)
    .map((key) => backend.get(key))
    .filter((summary): summary is StepSummary => Boolean(summary));
}

function stepHasBackendSummary(step: UserStep, backend: Map<string, StepSummary>) {
  return stepSummariesFor(step, backend).length > 0;
}

function mergedStepStatus(summaries: StepSummary[]): StepState {
  if (summaries.length === 0) return "pending";
  const statuses = summaries.map((summary) => normalizeStatus(summary.status));
  if (statuses.includes("running")) return "running";
  if (statuses.includes("failed")) return "failed";
  if (statuses.every((status) => status === "completed")) return "completed";
  return "pending";
}

function displayStepSummary(summaries: StepSummary[]) {
  return (
    cleanStreamLine(summaries.find((summary) => normalizeStatus(summary.status) === "running")?.summary) ||
    cleanStreamLine(summaries.find((summary) => normalizeStatus(summary.status) === "failed")?.summary) ||
    cleanStreamLine([...summaries].reverse().find((summary) => summary.summary)?.summary) ||
    null
  );
}

export function getActiveStepIndex(rows: StepRow[], task?: Task) {
  if (task?.status === "succeeded") return rows.length - 1;
  const failed = rows.findIndex((row) => row.status === "failed");
  if (failed >= 0) return failed;
  const running = rows.findIndex((row) => row.status === "running");
  if (running >= 0) return running;
  const lastCompleted = rows.reduce((last, row, index) => (row.status === "completed" ? index : last), -1);
  return Math.min(lastCompleted + 1, rows.length - 1);
}

function normalizeStatus(status?: string): StepState {
  if (status === "completed" || status === "running" || status === "failed") return status;
  if (status === "done") return "completed";
  return "pending";
}

export function getBrief(task: Task | undefined, uploadedFiles: UploadedAsset[], generatedAssetCount = 0) {
  const title = task?.game_title || task?.game?.title || summarizeIdea(task?.idea) || summarizeIdea(uploadedFiles[0]?.name) || "Untitled game";
  const source = `${title} ${task?.idea || ""}`.toLowerCase();
  const genre = inferGenre(source);
  const style = inferStyle(source);
  const uploadedAssetCount = task?.assets?.filter((asset) => asset.type === "uploaded").length ?? uploadedFiles.length;
  const assetCount = uploadedAssetCount + generatedAssetCount;
  const runtime = task?.dimension === "3d" ? "3D · WebGL" : task ? "2D · Canvas" : "Browser runtime";
  return { title, assetCount, genre, style, runtime };
}

function summarizeIdea(value?: string) {
  if (!value) return "";
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  return cleaned.length > 34 ? `${cleaned.slice(0, 31)}...` : cleaned;
}

function inferGenre(source: string) {
  if (source.includes("puzzle") || source.includes("logic")) return "Puzzle";
  if (source.includes("racing") || source.includes("race") || source.includes("drift")) return "Racing";
  if (source.includes("runner") || source.includes("dodge") || source.includes("arcade")) return "Arcade";
  if (source.includes("rpg") || source.includes("quest")) return "RPG";
  return "Arcade";
}

function inferStyle(source: string) {
  if (source.includes("cyberpunk") || source.includes("neon")) return "Cyberpunk";
  if (source.includes("forest") || source.includes("magic") || source.includes("fantasy")) return "Fantasy";
  if (source.includes("pixel")) return "Pixel";
  if (source.includes("cozy")) return "Cozy";
  return "AI generated";
}

export function getProgressTitle(task?: Task) {
  if (task?.status === "succeeded") return "Game ready";
  if (task?.status === "failed" && task.error_code === "ASSET_GENERATION_FAILED") return "Waiting for image retry";
  if (task?.status === "failed") return "Generation stopped";
  if (task?.status === "cancelled") return "Task cancelled";
  return "Creating your game";
}

export function getCurrentIssue(task: Task | undefined, activeStep?: StepRow) {
  if (!task) return null;
  if (task.status === "failed") {
    const imageRetryRequired = task.error_code === "ASSET_GENERATION_FAILED";
    return {
      level: "error" as const,
      title: imageRetryRequired ? "Image generation needs retry" : "Issue found",
      message: task.error || "Build validation could not pass after repair attempts.",
    };
  }
  if (task.status === "cancelled") {
    return {
      level: "warning" as const,
      title: "Cancelled",
      message: "This task was stopped before preview generation completed.",
    };
  }
  if (task.repair_attempts && activeStep?.key === "build_validation") {
    return {
      level: "warning" as const,
      title: "Issue found - Auto-repairing",
      message: `Repair attempt ${task.repair_attempts} of ${task.max_repair_attempts || 2} - ${latestReadableLog(task) || "Fixing a runtime validation issue."}`,
    };
  }
  if (task.replan_attempts && activeStep?.key === "build_validation") {
    return {
      level: "warning" as const,
      title: "Design adjusted",
      message: `Replanning a simpler playable version - Attempt ${task.replan_attempts} of ${task.max_replan_attempts || 1}.`,
    };
  }
  if (activeStep?.key === "gameplay_qa" && activeStep.status === "running") {
    return {
      level: "warning" as const,
      title: "Playtest running",
      message: latestReadableLog(task) || "Checking restart, input response, scoring, and difficulty before preview.",
    };
  }
  if (activeStep?.key === "gameplay_qa" && activeStep.status === "failed") {
    return {
      level: "error" as const,
      title: "Gameplay issue found",
      message: latestReadableLog(task) || "The generated game needs a balance or logic repair before publishing.",
    };
  }
  return null;
}

function latestReadableLog(task?: Task) {
  const logs = visibleAgentLogs(task);
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const line = logs[index].message || logs[index].lines.at(-1);
    if (line) return friendlyMessage(line);
  }
  return "";
}

export function getRecentUpdates(task: Task | undefined, now: number) {
  const logs = visibleAgentLogs(task);
  const updates = logs
    .filter((log) => log.message || log.lines.length)
    .slice(-3)
    .reverse()
    .map((log) => ({
      level: log.status === "failed" ? ("error" as const) : log.status === "completed" ? ("success" as const) : ("info" as const),
      message: friendlyMessage(log.message || log.lines.at(-1) || "Task updated"),
      time: formatRelative(log.created_at || task?.updated_at || task?.created_at, now) || "just now",
    }));

  if (updates.length > 0) return updates;
  // 没有真实日志时不编造系统状态（"sandbox ready / pipeline connected" 之类
  // 会在故障时显示一切正常）—— 只说我们真正知道的事。
  if (!task) {
    return [{ level: "info" as const, message: "Loading task…", time: "now" }];
  }
  if (task.status === "succeeded") {
    return [
      { level: "success" as const, message: "Preview ready", time: formatRelative(task.finished_at || task.updated_at, now) || "just now" },
    ];
  }
  return [
    { level: "info" as const, message: "Generation task created", time: formatRelative(task.created_at, now) || "just now" },
    { level: "info" as const, message: "Waiting for the first agent update", time: "now" },
  ];
}

export function friendlyMessage(message: string) {
  const compact = message.replace(/\s+/g, " ").trim();
  if (isStreamTokenLine(compact)) return "";
  const lower = compact.toLowerCase();
  if (lower.includes("gameplay planning") || lower.includes("brief expansion") || lower.includes("intent spec")) return "Turning your idea into a playable game brief";
  if (lower.startsWith("tags:")) return "Core gameplay and themes identified";
  if (lower.startsWith("runtime:")) return "Browser runtime selected";
  if (lower.includes("retrieval strategy: none")) return "Using your brief without external references";
  if (lower.includes("normalized prompt")) return "Game brief normalized for generation";
  if (lower.includes("repair")) return "Repair attempt started";
  if (lower.includes("playtest") || lower.includes("gameplay") || lower.includes("qa")) return "Gameplay playtest updated";
  if (lower.includes("difficulty") || lower.includes("balance")) return "Difficulty balance adjusted";
  if (lower.includes("validation") && lower.includes("issue")) return "Validation found an issue";
  if (lower.includes("asset")) return "Assets processed successfully";
  if (lower.includes("manifest")) return "Manifest uploaded";
  if (lower.includes("preview")) return "Preview prepared";
  if (lower.includes("design")) return "Game designed";
  if (lower.includes("code")) return "Files generated";
  return compact.length > 86 ? `${compact.slice(0, 83)}...` : compact || "Task updated";
}

export function getGameplayQaStatus(task?: Task): StepState | null {
  const summaries = (task?.step_summaries ?? []).filter((summary) => GAMEPLAY_STEP_KEYS.includes(summary.step as (typeof GAMEPLAY_STEP_KEYS)[number]));
  return summaries.length > 0 ? mergedStepStatus(summaries) : null;
}

export function gameplayRuntimeLabel(status: StepState) {
  if (status === "completed") return "Playtest passed";
  if (status === "running") return "Playtest running";
  if (status === "failed") return "Playtest needs repair";
  return "Playtest pending";
}

export function gameplayTechLabel(status: StepState) {
  if (status === "completed") return "Passed";
  if (status === "running") return "Running";
  if (status === "failed") return "Needs repair";
  return "Pending";
}

export function isActiveTask(status?: string) {
  return status === "pending" || status === "running";
}
