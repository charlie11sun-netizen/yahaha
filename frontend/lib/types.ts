export interface User {
  id: string;
  name: string;
  email: string;
  init: string;
}

export interface Game {
  id: string;
  title: string;
  summary: string;
  genre: string;
  cover: string;
  version: string;
  source: string;
  from_create: boolean;
  status: string;
  author: string;
  author_init: string;
  tags: string[];
  plays: number;
  plays_str: string;
  likes: number;
  likes_str: string;
  published_at: string | null;
  date: string;
  manifest_url: string;
  oss_path: string;
  prompt?: string | null;
  bundle_url?: string;
  liked?: boolean;
  favorited?: boolean;
}

export interface Step {
  seq: number;
  agent: string;
  name: string;
  status: string;
  logs: string[];
}

export interface StepSummary {
  step: string;
  title: string;
  status: "pending" | "running" | "completed" | "failed";
  summary?: string | null;
}

export interface AgentLogItem {
  agent_name: string;
  step: string;
  message: string;
  duration?: string | null;
  status: string;
  lines: string[];
}

export interface DesignPreview {
  title: string;
  fields: { label: string; value: string }[];
}

export interface TaskAsset {
  name: string;
  type: "uploaded" | "generated" | "default";
  status: string;
  kind?: string;
  url?: string;
}

export interface Task {
  id: string;
  status: string;
  current_step: number;
  current_agent?: string | null;
  repair_attempts?: number;
  replan_attempts?: number;
  tokens: number;
  error: string | null;
  error_code?: string | null;
  idea: string;
  progress?: number;
  game_title?: string;
  manifest_url?: string | null;
  preview_url?: string | null;
  step_summaries?: StepSummary[];
  design?: DesignPreview | null;
  assets?: TaskAsset[];
  logs?: AgentLogItem[];
  steps: Step[];
  game: Game | null;
}

export interface UploadedAsset {
  id: string;
  name: string;
  kind: string;
  size: number;
  url: string;
}
