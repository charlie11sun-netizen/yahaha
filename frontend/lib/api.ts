import type {
  Comment,
  Game,
  MemoryItem,
  MemoryProfile,
  MemoryProfileVersion,
  MemorySettings,
  Task,
  UploadedAsset,
  User,
} from "./types";

export const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const t = localStorage.getItem("pf_token");
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// Forward the site-gate token to the (cross-origin) backend. After unlocking,
// the gate stores it in the readable `pf_gate_token` cookie; when the gate is
// disabled the cookie is absent and no header is sent.
function gateHeader(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const m = document.cookie.match(/(?:^|;\s*)pf_gate_token=([^;]+)/);
  return m ? { "X-Gate-Token": decodeURIComponent(m[1]) } : {};
}

async function req<T>(
  path: string,
  opts: { method?: string; json?: unknown; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...authHeader(), ...gateHeader() };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  const res = await fetch(BASE + path, {
    method: opts.method || (body ? "POST" : "GET"),
    headers,
    body,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const d = (await res.json()).detail;
      if (typeof d === "string") detail = d;
      // FastAPI 422 的 detail 是数组 —— 拼成可读文案而不是 "[object Object]"
      else if (Array.isArray(d)) detail = d.map((it) => it?.msg).filter(Boolean).join("; ");
    } catch {
      /* ignore */
    }
    handleSessionExpiry(res.status, path);
    throw new ApiError(res.status, detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// 会话失效的全局出口：带着 token 却收到 401（过期/被吊销）→ 清 token 并跳登录，
// 登录后回跳原页面。/auth/* 不在此列：登录/注册的 401 是密码错误，挂载时的
// /auth/me 探测在公开页也会跑（由 AuthProvider 自己清 token，不该强制跳转）。
function handleSessionExpiry(status: number, path: string) {
  if (status !== 401 || typeof window === "undefined") return;
  if (path.startsWith("/auth/")) return;
  if (!localStorage.getItem("pf_token")) return;
  localStorage.removeItem("pf_token");
  if (!window.location.pathname.startsWith("/login")) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
  }
}

export const api = {
  register: (email: string, password: string, display_name: string) =>
    req<{ token: string; user: User }>("/auth/register", { json: { email, password, display_name } }),
  login: (email: string, password: string) =>
    req<{ token: string; user: User }>("/auth/login", { json: { email, password } }),
  me: () => req<User>("/auth/me"),
  updateMe: (patch: { display_name?: string; email?: string; avatar?: string }) =>
    req<User>("/auth/me", { method: "PATCH", json: patch }),
  changePassword: (current_password: string, new_password: string) =>
    req<{ ok: boolean }>("/auth/change-password", { json: { current_password, new_password } }),
  deleteAccount: () => req<{ ok: boolean }>("/auth/me", { method: "DELETE" }),
  logout: () => req("/auth/logout", { method: "POST" }),
  oauthDemo: (provider: string) =>
    req<{ token: string; user: User }>(`/auth/oauth/${provider}/demo`, { method: "POST" }),
  oauthProviders: () => req<Record<string, boolean>>("/auth/oauth/providers"),
  oauthStartUrl: (provider: string) => `${BASE}/auth/oauth/${provider}/start`,

  games: (q = "", tag = "All", opts: { sort?: string; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams({ q, tag });
    if (opts.sort) params.set("sort", opts.sort);
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.offset != null) params.set("offset", String(opts.offset));
    return req<{ items: Game[]; total: number; has_more?: boolean }>(`/games?${params.toString()}`);
  },
  game: (id: string) => req<Game>(`/games/${id}`),
  myGames: () => req<{ items: Game[] }>("/me/games"),
  myFavorites: () => req<{ items: Game[] }>("/me/favorites"),
  preview: (id: string) => req<Game>(`/games/${id}/preview`),
  stats: () => req<{ game_count: number; total_plays: number }>("/stats"),
  tags: () => req<{ tags: string[] }>("/tags"),
  play: (id: string) => req<{ plays: number; plays_str: string }>(`/games/${id}/play`, { method: "POST" }),
  publish: (id: string) => req<Game>(`/games/${id}/publish`, { method: "POST" }),
  unpublish: (id: string) => req<Game>(`/games/${id}/unpublish`, { method: "POST" }),
  updateGame: (id: string, patch: { title?: string; summary?: string; tags?: string[] }) =>
    req<Game>(`/games/${id}`, { method: "PATCH", json: patch }),
  deleteGame: (id: string) => req<{ ok: boolean }>(`/games/${id}`, { method: "DELETE" }),
  like: (id: string) => req<{ liked: boolean; likes: number }>(`/games/${id}/like`, { method: "POST" }),
  unlike: (id: string) => req<{ liked: boolean; likes: number }>(`/games/${id}/like`, { method: "DELETE" }),
  favorite: (id: string) => req<{ favorited: boolean }>(`/games/${id}/favorite`, { method: "POST" }),
  unfavorite: (id: string) => req<{ favorited: boolean }>(`/games/${id}/favorite`, { method: "DELETE" }),

  // social / discovery
  userProfile: (id: string) =>
    req<{
      id: string; name: string; init: string; game_count: number; total_plays: number;
      followers: number; following: number; is_following: boolean; is_self: boolean;
    }>(`/users/${id}`),
  userGames: (id: string) => req<{ items: Game[] }>(`/users/${id}/games`),
  followUser: (id: string) => req<{ following: boolean }>(`/users/${id}/follow`, { method: "POST" }),
  unfollowUser: (id: string) => req<{ following: boolean }>(`/users/${id}/follow`, { method: "DELETE" }),
  comments: (id: string) => req<{ items: Comment[] }>(`/games/${id}/comments`),
  addComment: (id: string, body: string) => req<Comment>(`/games/${id}/comments`, { json: { body } }),
  deleteComment: (gameId: string, commentId: string) =>
    req<{ ok: boolean }>(`/games/${gameId}/comments/${commentId}`, { method: "DELETE" }),
  relatedGames: (id: string) => req<{ items: Game[] }>(`/games/${id}/related`),
  leaderboard: (id: string) =>
    req<{ items: { rank: number; name: string; points: number; ago: string }[] }>(`/games/${id}/leaderboard`),
  submitScore: (id: string, points: number, player_name?: string) =>
    req<{ ok: boolean }>(`/games/${id}/score`, { json: { points, player_name } }),
  gameManifest: (id: string) =>
    req<{ entry?: string; runtime?: string; sha256?: string; _source?: string; _url?: string }>(`/games/${id}/manifest`),

  upload: (files: FileList | File[]) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    return req<{ assets: UploadedAsset[] }>("/uploads", { form: fd });
  },
  createTask: (idea: string, asset_ids: string[], dimension: "2d" | "3d" = "2d") =>
    req<{ task_id: string }>("/tasks", { json: { idea, asset_ids, dimension } }),
  tasks: () => req<{ items: Task[] }>("/tasks"),
  task: (id: string) => req<Task>(`/tasks/${id}`),
  retryTask: (id: string) => req<{ task_id: string }>(`/tasks/${id}/retry`, { method: "POST" }),
  reviseTask: (id: string, feedback: string) =>
    req<{ task_id: string }>(`/tasks/${id}/revise`, { json: { feedback } }),
  cancelTask: (id: string) => req<Task>(`/tasks/${id}/cancel`, { method: "POST" }),
  deleteTask: (id: string) => req<{ ok: boolean }>(`/tasks/${id}`, { method: "DELETE" }),

  memories: (params: { scope_type?: string; scope_id?: string; category?: string; status?: string } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) qs.set(key, value);
    });
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<{ items: MemoryItem[] }>(`/memory${suffix}`);
  },
  createMemory: (body: {
    scope_type: "user" | "game" | "task";
    scope_id?: string | null;
    category: MemoryItem["category"];
    raw_text: string;
    extracted_text?: string | null;
    importance?: number;
    pinned?: boolean;
  }) => req<MemoryItem>("/memory", { json: body }),
  updateMemory: (id: string, patch: Partial<Pick<MemoryItem, "category" | "raw_text" | "extracted_text" | "importance" | "pinned" | "status">>) =>
    req<MemoryItem>(`/memory/${id}`, { method: "PATCH", json: patch }),
  deleteMemory: (id: string) => req<{ ok: boolean }>(`/memory/${id}`, { method: "DELETE" }),
  memorySettings: () => req<MemorySettings>("/memory/settings"),
  updateMemorySettings: (patch: Partial<MemorySettings>) =>
    req<MemorySettings>("/memory/settings", { method: "PATCH", json: patch }),
  memoryProfiles: (params: { status?: string; scope_type?: string; scope_id?: string } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) qs.set(key, value);
    });
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<{ items: MemoryProfile[] }>(`/memory/profiles${suffix}`);
  },
  memoryProfileHistory: (id: string) =>
    req<{ items: MemoryProfileVersion[] }>(`/memory/profiles/${id}/history`),
  updateMemoryProfile: (id: string, patch: { value_text?: string; summary_text?: string }) =>
    req<MemoryProfile>(`/memory/profiles/${id}`, { method: "PATCH", json: patch }),
};
