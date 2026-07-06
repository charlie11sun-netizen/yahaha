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
  remixed_from_game_id?: string | null;
  remixed_from_version?: string | null;
  remixed_from?: {
    id: string;
    title: string;
    author: string;
    version?: string | null;
  } | null;
  remix_count?: number;
}

export interface GameVersion {
  version: string;
  created_at?: string | null;
  size_bytes: number;
  sha256: string;
  is_current: boolean;
}

export interface GameManifestFile {
  path: string;
  url?: string;
  sha256?: string;
}

export interface GameManifest {
  entry?: string;
  entry_url?: string;
  runtime?: string;
  sha256?: string;
  title?: string;
  files?: GameManifestFile[];
  _source?: string;
  _url?: string;
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
  task_kind?: "generation" | "revision" | "remix";
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

export interface MemoryProfile {
  id: string;
  scope_type: "user" | "game" | "task";
  scope_id?: string | null;
  profile_key: string;
  category: MemoryItem["category"];
  value_text: string;
  summary_text: string;
  evidence_span: string;
  confidence: number;
  scope_confidence: number;
  explicitness: "manual" | "explicit" | "inferred";
  status: "active" | "candidate" | "superseded" | "deleted";
  source_memory_id: string;
  conflicts_with_id?: string | null;
  support_count: number;
  utility_score: number;
  utility_observation_count: number;
  last_supported_at?: string | null;
  expires_at?: string | null;
  version: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MemoryProfileVersion {
  id: string;
  profile_id: string;
  version: number;
  operation: string;
  snapshot: Record<string, unknown>;
  source_memory_id?: string | null;
  reason?: string | null;
  created_at?: string | null;
}
