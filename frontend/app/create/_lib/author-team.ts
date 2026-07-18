import type { Task } from "@/lib/types";

export type AuthorTeamRoleStatus = "pending" | "running" | "completed" | "partial" | "failed" | "skipped";

export type AuthorTeamRoleProgress = {
  name: AuthorTeamRoleName;
  label: string;
  detail: string;
  status: AuthorTeamRoleStatus;
};

export type AuthorTeamProgress = {
  roles: AuthorTeamRoleProgress[];
  activeRole: AuthorTeamRoleProgress | null;
  currentLabel: string;
  currentDetail: string;
  completedCount: number;
};

type AuthorTeamRoleName =
  | "DesignContractAgent"
  | "RulesAndSimulationCoder"
  | "WorldAndContentCoder"
  | "PresentationAndInteractionCoder"
  | "IntegrationAgent";

const ROLE_DEFINITIONS: ReadonlyArray<Omit<AuthorTeamRoleProgress, "status">> = [
  {
    name: "DesignContractAgent",
    label: "Design contract",
    detail: "Freezing shared state, events, module ownership, and acceptance checks.",
  },
  {
    name: "RulesAndSimulationCoder",
    label: "Rules & simulation",
    detail: "Implementing gameplay rules, simulation, scoring, and win/loss behavior.",
  },
  {
    name: "WorldAndContentCoder",
    label: "World & content",
    detail: "Implementing actors, levels, items, encounters, and other playable content.",
  },
  {
    name: "PresentationAndInteractionCoder",
    label: "Presentation & input",
    detail: "Implementing controls, HUD, feedback, camera, audio, and accessibility.",
  },
  {
    name: "IntegrationAgent",
    label: "Integration",
    detail: "Wiring the owned modules into a playable scene and running project checks.",
  },
];

const ROLE_NAMES = new Set<AuthorTeamRoleName>(ROLE_DEFINITIONS.map((role) => role.name));

function eventRecord(event: unknown): Record<string, unknown> | null {
  return event && typeof event === "object" && !Array.isArray(event) ? (event as Record<string, unknown>) : null;
}

function eventString(event: Record<string, unknown>, key: string) {
  const value = event[key];
  return typeof value === "string" ? value : "";
}

function roleName(value: string): AuthorTeamRoleName | null {
  return ROLE_NAMES.has(value as AuthorTeamRoleName) ? (value as AuthorTeamRoleName) : null;
}

function roleLabel(name: AuthorTeamRoleName) {
  return ROLE_DEFINITIONS.find((role) => role.name === name)?.label || name;
}

function statusFromValue(value: string): AuthorTeamRoleStatus | null {
  if (["running", "streaming", "role_started"].includes(value)) return "running";
  if (["completed", "done", "role_finished", "fallback"].includes(value)) return "completed";
  if (["partial", "budget_exhausted", "role_budget_exhausted"].includes(value)) return "partial";
  if (["failed", "error", "stopped", "integration_unavailable", "integration_incomplete"].includes(value)) return "failed";
  if (value === "skipped") return "skipped";
  return null;
}

export function authorTeamEventMessage(event: unknown) {
  const record = eventRecord(event);
  if (!record) return "";
  const type = eventString(record, "type");
  const phase = eventString(record, "phase");
  const role = roleName(eventString(record, "role") || eventString(record, "agent"));

  if (type === "turn_state" && role) {
    if (phase === "streaming") return `${roleLabel(role)} is in progress`;
    if (phase === "completed") return `${roleLabel(role)} completed`;
    if (phase === "error") return `${roleLabel(role)} stopped`;
  }
  if (type === "role_budget_exhausted" && role) {
    return `${roleLabel(role)} reached its turn budget; partial work was preserved`;
  }
  if (type !== "author_team") return "";
  if (role) {
    const status = statusFromValue(eventString(record, "status") || phase);
    if (status === "running") return `${roleLabel(role)} is in progress`;
    if (status === "completed") return `${roleLabel(role)} completed`;
    if (status === "partial") return `${roleLabel(role)} preserved partial work`;
    if (status === "failed") return `${roleLabel(role)} needs fallback`;
    if (status === "skipped") return `${roleLabel(role)} skipped`;
  }
  if (phase === "start") return "Implementation team started";
  if (phase === "contract_frozen") return "Game implementation contract frozen";
  if (phase === "candidate_merge") return "Merging owned implementation modules";
  if (phase === "integration_unavailable") return "Integration fallback required";
  if (phase === "integration_incomplete") return "Integration needs outer repair";
  return eventString(record, "message");
}

export function getAuthorTeamProgress(task?: Task): AuthorTeamProgress | null {
  const statuses = new Map<AuthorTeamRoleName, AuthorTeamRoleStatus>(
    ROLE_DEFINITIONS.map((role) => [role.name, "pending"]),
  );
  let seenTeam = false;
  let activeRoleName: AuthorTeamRoleName | null = null;

  for (const log of task?.logs ?? []) {
    const entries = log.entries?.length
      ? log.entries
      : (log.lines.length ? log.lines : [log.message]).map((line) => ({ line, event: null }));
    for (const entry of entries) {
      const event = eventRecord(entry.event);
      if (!event) continue;
      const type = eventString(event, "type");
      const phase = eventString(event, "phase");
      const explicitRole = roleName(eventString(event, "role") || eventString(event, "agent"));

      if (type === "author_team") seenTeam = true;
      if (explicitRole) {
        seenTeam = true;
        activeRoleName = explicitRole;
        const status = statusFromValue(eventString(event, "status") || phase);
        if (status) statuses.set(explicitRole, status);
      } else if (seenTeam && activeRoleName && type === "turn_state") {
        const status = statusFromValue(eventString(event, "status") || phase);
        if (status) statuses.set(activeRoleName, status);
      } else if (seenTeam && activeRoleName && (type === "error" || (type === "notice" && eventString(event, "status") === "stopped"))) {
        statuses.set(activeRoleName, "failed");
      }

      if (type === "author_team" && phase === "contract_frozen") {
        statuses.set("DesignContractAgent", "completed");
      }
      if (type === "author_team" && ["integration_unavailable", "integration_incomplete"].includes(phase)) {
        statuses.set("IntegrationAgent", "failed");
        activeRoleName = "IntegrationAgent";
      }
    }
  }

  if (!seenTeam) return null;

  // Role-level warnings are intermediate evidence.  The durable task outcome
  // wins once build, QA, and publish have succeeded.
  if (task?.status === "succeeded") {
    ROLE_DEFINITIONS.forEach((role) => statuses.set(role.name, "completed"));
    activeRoleName = null;
  }

  const roles = ROLE_DEFINITIONS.map((role) => ({ ...role, status: statuses.get(role.name) || "pending" }));
  const activeRole = [...roles].reverse().find((role) => role.status === "running") || null;
  const failedRole = [...roles].reverse().find((role) => role.status === "failed") || null;
  const partialRole = [...roles].reverse().find((role) => role.status === "partial") || null;
  const integration = roles.find((role) => role.name === "IntegrationAgent");
  const completedCount = roles.filter((role) => role.status === "completed" || role.status === "skipped").length;

  if (activeRole) {
    return {
      roles,
      activeRole,
      currentLabel: activeRole.label,
      currentDetail: activeRole.detail,
      completedCount,
    };
  }
  if (integration?.status === "completed") {
    return {
      roles,
      activeRole: null,
      currentLabel: "Implementation team complete",
      currentDetail: "The owned modules have been integrated and handed to the build gate.",
      completedCount,
    };
  }
  if (failedRole) {
    return {
      roles,
      activeRole: null,
      currentLabel: `${failedRole.label} fallback`,
      currentDetail: "The outer build and repair loop will finish any missing implementation work.",
      completedCount,
    };
  }
  if (partialRole) {
    return {
      roles,
      activeRole: null,
      currentLabel: `${partialRole.label} budget reached`,
      currentDetail: "Its valid partial work was preserved for integration; this is not a repair attempt.",
      completedCount,
    };
  }
  return {
    roles,
    activeRole: null,
    currentLabel: "Implementation team",
    currentDetail: "Preparing isolated role workspaces from the frozen project snapshot.",
    completedCount,
  };
}
