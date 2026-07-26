import type { StepSummary, Task, UploadedAsset } from "@/lib/types";
import { cleanStreamLine, isStreamTokenLine, visibleAgentLogs } from "./agent-activity";
import { activityMessageFromEvent, logEntries, repairAttemptFromEvent } from "./agent-events";
import { formatRelative } from "./create-time";

export const GAMEPLAY_STEP_KEYS = ["gameplay_qa", "gameplay_repair"] as const;
export type UserStep = { key: string; label: string; backendKeys?: readonly string[]; optional?: boolean };

// The backend graph is deliberately more detailed than the user-facing
// timeline.  Keep the product language stable while grouping the nodes that
// belong to one phase.  Optional rows are only rendered when that branch was
// actually taken (for example repair/replan or gameplay repair).
const USER_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Idea checked" },
  { key: "memory_retrieval", label: "Context retrieved" },
  { key: "intent_spec", label: "Game spec created" },
  { key: "gameplay_planning", label: "Gameplay planned", backendKeys: ["gameplay_planning", "brief_expansion", "mechanic_planner"] },
  { key: "archetype_router", label: "Template selected" },
  { key: "game_design", label: "Game designed" },
  { key: "content_plan", label: "Content planned" },
  { key: "balance_plan", label: "Balance tuned" },
  { key: "design_contract", label: "Design contract frozen" },
  { key: "contract_gate", label: "Contract verified" },
  { key: "asset_processing", label: "Assets prepared" },
  { key: "asset_generation", label: "Game assets generated" },
  { key: "code_generation", label: "Files generated" },
  { key: "project_build", label: "Runtime built" },
  { key: "build_validation", label: "Build validated", backendKeys: ["build_validation", "static_validation"] },
  { key: "repair_code", label: "Build repaired", optional: true },
  { key: "replan_game_design", label: "Design simplified", optional: true },
  { key: "gameplay_qa", label: "Playtesting game", backendKeys: ["gameplay_qa"], optional: true },
  { key: "gameplay_repair", label: "Playtest repaired", optional: true },
  { key: "publish_artifact", label: "Preparing preview" },
  { key: "memory_update", label: "Saving memory", optional: true },
  { key: "ready", label: "Ready to publish" },
];
const USER_REVISION_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Feedback checked" },
  { key: "memory_retrieval", label: "Context retrieved" },
  { key: "feedback_understanding", label: "Feedback understood" },
  { key: "design_contract", label: "Design contract frozen" },
  { key: "contract_gate", label: "Contract verified" },
  { key: "asset_processing", label: "Assets prepared", optional: true },
  { key: "asset_generation", label: "Game assets generated", optional: true },
  { key: "code_revision", label: "Existing files revised" },
  { key: "project_build", label: "Runtime built" },
  { key: "build_validation", label: "Validating changes" },
  { key: "revision_repair", label: "Revision repaired", optional: true },
  { key: "gameplay_qa", label: "Regression playtest" },
  { key: "gameplay_repair", label: "Playtest repaired", optional: true },
  { key: "publish_revision", label: "Saving new preview" },
  { key: "memory_update", label: "Saving memory", optional: true },
  { key: "ready", label: "Ready to publish" },
];
const USER_REMIX_STEPS: UserStep[] = [
  { key: "safety_intake", label: "Remix checked" },
  { key: "memory_retrieval", label: "Context retrieved" },
  { key: "feedback_understanding", label: "Remix goal understood" },
  { key: "design_contract", label: "Design contract frozen" },
  { key: "contract_gate", label: "Contract verified" },
  { key: "asset_processing", label: "Assets prepared", optional: true },
  { key: "asset_generation", label: "Game assets generated", optional: true },
  { key: "code_revision", label: "Source files transformed" },
  { key: "project_build", label: "Runtime built" },
  { key: "build_validation", label: "Validating remix" },
  { key: "revision_repair", label: "Remix repaired", optional: true },
  { key: "gameplay_qa", label: "Playtesting remix" },
  { key: "gameplay_repair", label: "Playtest repaired", optional: true },
  { key: "publish_remix", label: "Saving remix preview" },
  { key: "memory_update", label: "Saving memory", optional: true },
  { key: "ready", label: "Ready to publish" },
];

export type StepState = "pending" | "running" | "completed" | "failed";
export type StepRow = { key: string; label: string; status: StepState; summary?: string | null };

const STEP_KEY_BY_AGENT: Record<string, string> = {
  SafetyIntakeAgent: "safety_intake",
  MemoryRetrievalAgent: "memory_retrieval",
  IntentSpecAgent: "intent_spec",
  GameplayPlanningAgent: "gameplay_planning",
  BriefExpansionAgent: "brief_expansion",
  MechanicPlannerAgent: "mechanic_planner",
  ArchetypeRouterAgent: "archetype_router",
  AssetAgent: "asset_processing",
  GameAssetGenerationAgent: "asset_generation",
  GameDesignAgent: "game_design",
  ContentPlanAgent: "content_plan",
  BalanceAgent: "balance_plan",
  DesignContractCompilerAgent: "design_contract",
  ContractGateAgent: "contract_gate",
  GameCodeAgent: "code_generation",
  ProjectBuildAgent: "project_build",
  BuildValidateAgent: "build_validation",
  GameCodeAgentRepair: "repair_code",
  GameDesignAgentReplan: "replan_game_design",
  GameplayQAAgent: "gameplay_qa",
  GameplayRepairAgent: "gameplay_repair",
  PublishArtifactAgent: "publish_artifact",
  FeedbackUnderstandingAgent: "feedback_understanding",
  CodeRevisionAgent: "code_revision",
  CodeRevisionRepairAgent: "revision_repair",
  PublishRevisionAgent: "publish_revision",
  PublishRemixAgent: "publish_remix",
  MemoryUpdateAgent: "memory_update",
};

const STEP_KEY_BY_LABEL: Record<string, string> = {
  "Safety Intake": "safety_intake",
  "Retrieve Memory": "memory_retrieval",
  "Intent Spec": "intent_spec",
  "Gameplay Planning": "gameplay_planning",
  "Brief Expansion": "brief_expansion",
  "Mechanic Planner": "mechanic_planner",
  "Archetype Router": "archetype_router",
  "Asset Processing": "asset_processing",
  "Generate Game Assets": "asset_generation",
  "Game Design": "game_design",
  "Content Plan": "content_plan",
  "Balance Plan": "balance_plan",
  "Design Contract": "design_contract",
  "Contract Gate": "contract_gate",
  "Code Generation": "code_generation",
  "Project Build": "project_build",
  "Build Validation": "build_validation",
  "Repair Code": "repair_code",
  "Replan Game Design": "replan_game_design",
  "Gameplay QA": "gameplay_qa",
  "Gameplay Repair": "gameplay_repair",
  "Publish Artifact": "publish_artifact",
  "Understand Feedback": "feedback_understanding",
  "Revise Existing Code": "code_revision",
  "Repair Revision": "revision_repair",
  "Save Preview Version": "publish_revision",
  "Save Remix": "publish_remix",
  "Update Memory": "memory_update",
};

export function buildStepRows(task?: Task): StepRow[] {
  const backend = taskStepSummaries(task);
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

/**
 * `step_summaries` is the compact API projection. During an old server
 * rollout it may not know about a newly-added graph node, while the detailed
 * `steps` array and SSE delta already do. Prefer the detailed execution record
 * for known nodes and use summaries as the compatibility fallback.
 */
function taskStepSummaries(task?: Task) {
  const summaries = new Map<string, StepSummary>();
  (task?.step_summaries ?? []).forEach((summary) => summaries.set(summary.step, summary));

  const detailed = [...(task?.steps ?? [])].sort((left, right) => (left.seq ?? 0) - (right.seq ?? 0));
  detailed.forEach((step) => {
    const key = STEP_KEY_BY_AGENT[step.agent] || STEP_KEY_BY_LABEL[step.name];
    if (!key) return;
    const summary = {
      step: key,
      title: step.name || key,
      status: step.status,
      summary: step.logs?.at(-1) || null,
    } satisfies StepSummary;
    summaries.set(key, summary);
  });
  return summaries;
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
  if (rows.length === 0) return 0;
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
  if (task?.status === "failed" && task.error_code === "MODEL_TIMEOUT") return "Waiting for retry (model connection interrupted)";
  if (task?.status === "failed" && task.failed_stage) return `Generation stopped at ${friendlyStepName(task.failed_stage)}`;
  if (task?.status === "failed") return "Generation stopped";
  if (task?.status === "cancelled") return "Task cancelled";
  return "Creating your game";
}

export function getCurrentIssue(task: Task | undefined, activeStep?: StepRow) {
  if (!task) return null;
  if (task.status === "failed") {
    const imageRetryRequired = task.error_code === "ASSET_GENERATION_FAILED";
    const streamRetryRequired = task.error_code === "MODEL_TIMEOUT";
    return {
      level: "error" as const,
      title: imageRetryRequired
        ? "Image generation needs retry"
        : streamRetryRequired
          ? "Model connection interrupted — retry resumes this step"
          : "Issue found",
      message: task.error || (task.failed_stage ? `Generation stopped during ${friendlyStepName(task.failed_stage)}.` : "Build validation could not pass after repair attempts."),
    };
  }
  if (task.status === "cancelled") {
    return {
      level: "warning" as const,
      title: "Cancelled",
      message: "This task was stopped before preview generation completed.",
    };
  }
  const repairAttempt = latestRunningRepairAttempt(task);
  if (repairAttempt) {
    const count = repairAttempt.maxAttempts
      ? `${repairAttempt.attempt} of ${repairAttempt.maxAttempts}`
      : String(repairAttempt.attempt || "").trim();
    return {
      level: "warning" as const,
      title: "Issue found - Auto-repairing",
      message: `Repair attempt${count ? ` ${count}` : ""} - ${latestReadableLog(task) || "Fixing a runtime validation issue."}`,
    };
  }
  if (activeStep?.key === "repair_code" && activeStep.status === "running") {
    return {
      level: "warning" as const,
      title: "Auto-repairing the build",
      message: activeStep.summary || `Repair attempt ${task.repair_attempts || 1} of ${task.max_repair_attempts || 2}.`,
    };
  }
  if (activeStep?.key === "replan_game_design" && activeStep.status === "running") {
    return {
      level: "warning" as const,
      title: "Simplifying the design",
      message: activeStep.summary || `Replan attempt ${task.replan_attempts || 1} of ${task.max_replan_attempts || 1}.`,
    };
  }
  if (activeStep?.key === "gameplay_repair" && activeStep.status === "running") {
    return {
      level: "warning" as const,
      title: "Repairing the playtest",
      message: activeStep.summary || "Tuning gameplay metrics and rebuilding the affected runtime.",
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

function latestRunningRepairAttempt(task?: Task) {
  const running = (task?.logs ?? []).filter((log) => log.status === "running");
  for (let logIndex = running.length - 1; logIndex >= 0; logIndex -= 1) {
    const entries = logEntries(running[logIndex]);
    for (let entryIndex = entries.length - 1; entryIndex >= 0; entryIndex -= 1) {
      const event = repairAttemptFromEvent(entries[entryIndex].event);
      if (event) return event;
    }
  }
  return null;
}

function latestReadableLog(task?: Task) {
  const logs = visibleAgentLogs(task);
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const entries = logEntries(logs[index]);
    for (let entryIndex = entries.length - 1; entryIndex >= 0; entryIndex -= 1) {
      const message = activityMessageFromEvent(entries[entryIndex].event);
      if (message) return message;
      const line = entries[entryIndex].line;
      if (line) return friendlyMessage(line);
    }
  }
  return "";
}

export function getRecentUpdates(task: Task | undefined, now: number) {
  const logs = visibleAgentLogs(task);
  const updates = logs
    .flatMap((log) =>
      logEntries(log).map((entry) => ({
        createdAt: "created_at" in entry ? entry.created_at : undefined,
        level: log.status === "failed" ? ("error" as const) : log.status === "completed" ? ("success" as const) : ("info" as const),
        message: activityMessageFromEvent(entry.event) || friendlyMessage(entry.line),
      })),
    )
    .filter((update) => update.message)
    .slice(-3)
    .reverse()
    .map((update) => ({
      level: update.level,
      message: update.message,
      time: formatRelative(update.createdAt || task?.updated_at || task?.created_at, now) || "just now",
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
  if (lower.includes("memoryretrieval") || lower.includes("retrieve memory") || lower.includes("retrieved memor")) return "Loading relevant creation memory";
  if (lower.includes("design contract")) return "Freezing the game design contract";
  if (lower.includes("contractgate") || lower.includes("contract gate")) return "Checking the design contract";
  if (lower.includes("gameassetgeneration") || lower.includes("generate game assets") || lower.includes("asset generation")) return "Generating and checking game assets";
  if (lower.includes("projectbuild") || lower.includes("project build") || lower.includes("runtime build")) return "Building the browser runtime";
  if (lower.includes("repaircode") || lower.includes("repair code")) return "Auto-repairing the generated build";
  if (lower.includes("replan") || lower.includes("simplif")) return "Simplifying the game design for a stable build";
  if (lower.includes("gameplayrepair") || lower.includes("gameplay repair")) return "Tuning the game after playtesting";
  if (lower.includes("designcontractagent")) return "Defining the game implementation contract";
  if (lower.includes("rulesandsimulationcoder") || lower.includes("rules & simulation")) return "Implementing game rules and simulation";
  if (lower.includes("worldandcontentcoder") || lower.includes("world & content")) return "Building the game world and playable content";
  if (lower.includes("presentationandinteractioncoder") || lower.includes("presentation & input")) return "Implementing controls, HUD, and game feedback";
  if (lower.includes("integrationagent") || lower.includes("implementation team complete")) return "Integrating game modules and running project checks";
  if (lower.includes("author team") || lower.includes("implementation team")) return "Game implementation team updated";
  if (lower.includes("gameplay planning") || lower.includes("brief expansion") || lower.includes("intent spec")) return "Turning your idea into a playable game brief";
  if (lower.startsWith("tags:")) return "Core gameplay and themes identified";
  if (lower.startsWith("runtime:")) return "Browser runtime selected";
  if (lower.includes("retrieval strategy: none")) return "Using your brief without external references";
  if (lower.includes("normalized prompt")) return "Game brief normalized for generation";
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

function friendlyStepName(value: string) {
  const key = value.trim().toLowerCase().replaceAll(" ", "_");
  const labels: Record<string, string> = {
    asset_generation: "asset generation",
    build_validation: "build validation",
    contract_gate: "contract verification",
    design_contract: "design contract",
    gameplay_qa: "gameplay QA",
    gameplay_repair: "gameplay repair",
    project_build: "runtime build",
    repair_code: "build repair",
    replan_game_design: "design replanning",
  };
  return labels[key] || value.replaceAll("_", " ");
}

export function getGameplayQaStatus(task?: Task): StepState | null {
  const summaries = Array.from(taskStepSummaries(task).values()).filter((summary) =>
    GAMEPLAY_STEP_KEYS.includes(summary.step as (typeof GAMEPLAY_STEP_KEYS)[number]),
  );
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
