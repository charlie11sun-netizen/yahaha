import type { Game, Task, UploadedAsset, User } from "./types";

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
  logout: () => req("/auth/logout", { method: "POST" }),
  oauthDemo: (provider: string) =>
    req<{ token: string; user: User }>(`/auth/oauth/${provider}/demo`, { method: "POST" }),

  games: (q = "", tag = "All") =>
    req<{ items: Game[]; total: number }>(
      `/games?q=${encodeURIComponent(q)}&tag=${encodeURIComponent(tag)}`,
    ),
  game: (id: string) => req<Game>(`/games/${id}`),
  myGames: () => req<{ items: Game[] }>("/me/games"),
  myFavorites: () => req<{ items: Game[] }>("/me/favorites"),
  preview: (id: string) => req<Game>(`/games/${id}/preview`),
  stats: () => req<{ game_count: number; total_plays: number }>("/stats"),
  tags: () => req<{ tags: string[] }>("/tags"),
  play: (id: string) => req<{ plays: number; plays_str: string }>(`/games/${id}/play`, { method: "POST" }),
  publish: (id: string) => req<Game>(`/games/${id}/publish`, { method: "POST" }),

  upload: (files: FileList | File[]) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    return req<{ assets: UploadedAsset[] }>("/uploads", { form: fd });
  },
  createTask: (idea: string, asset_ids: string[]) =>
    req<{ task_id: string }>("/tasks", { json: { idea, asset_ids } }),
  task: (id: string) => req<Task>(`/tasks/${id}`),
};
