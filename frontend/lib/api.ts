import type { Comment, Game, Task, UploadedAsset, User } from "./types";

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

async function req<T>(
  path: string,
  opts: { method?: string; json?: unknown; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...authHeader() };
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
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  register: (email: string, password: string, display_name: string) =>
    req<{ token: string; user: User }>("/auth/register", { json: { email, password, display_name } }),
  login: (email: string, password: string) =>
    req<{ token: string; user: User }>("/auth/login", { json: { email, password } }),
  me: () => req<User>("/auth/me"),
  updateMe: (patch: { display_name?: string; email?: string }) =>
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

  upload: (files: FileList | File[]) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    return req<{ assets: UploadedAsset[] }>("/uploads", { form: fd });
  },
  createTask: (idea: string, asset_ids: string[]) =>
    req<{ task_id: string }>("/tasks", { json: { idea, asset_ids } }),
  tasks: () => req<{ items: Task[] }>("/tasks"),
  task: (id: string) => req<Task>(`/tasks/${id}`),
  retryTask: (id: string) => req<{ task_id: string }>(`/tasks/${id}/retry`, { method: "POST" }),
  cancelTask: (id: string) => req<Task>(`/tasks/${id}/cancel`, { method: "POST" }),
  deleteTask: (id: string) => req<{ ok: boolean }>(`/tasks/${id}`, { method: "DELETE" }),
};
