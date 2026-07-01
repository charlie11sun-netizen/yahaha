export interface User {
  id: string;
  name: string;
  email: string;
  init: string;
  created_at?: string | null;
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
  author_id: string;
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
  created_at?: string;
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
  task_kind?: "generation" | "revision";
  base_game_id?: string | null;
  base_version?: string | null;
  feedback_text?: string | null;
  feedback_brief?: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  current_step: number;
  current_agent?: string | null;
  repair_attempts?: number;
  max_repair_attempts?: number;
  replan_attempts?: number;
  max_replan_attempts?: number;
  tokens: number;
  error: string | null;
  error_code?: string | null;
  idea: string;
  dimension?: "2d" | "3d";
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

export interface Comment {
  id: string;
  body: string;
  created_at?: string | null;
  ago: string;
  author: string;
  author_init: string;
  author_id: string;
}

export interface MemoryItem {
  id: string;
  scope_type: "user" | "game" | "task";
  scope_id?: string | null;
  category: "style" | "mechanics" | "controls" | "difficulty" | "content" | "constraints" | "feedback";
  raw_text: string;
  extracted_text?: string | null;
  source_type: string;
  source_task_id?: string | null;
  source_game_id?: string | null;
  source_version?: string | null;
  importance: number;
  confidence: number;
  pinned: boolean;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MemorySettings {
  enabled: boolean;
  allow_cross_game_memory: boolean;
  allow_memory_extraction: boolean;
  retention_days?: number | null;
}
