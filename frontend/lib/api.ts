import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./api-types";

export const BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("pf_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function gateHeader(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const match = document.cookie.match(/(?:^|;\s*)pf_gate_token=([^;]+)/);
  return match ? { "X-Gate-Token": decodeURIComponent(match[1]) } : {};
}

const sessionMiddleware: Middleware = {
  onRequest({ request }) {
    for (const [name, value] of Object.entries({ ...authHeader(), ...gateHeader() })) {
      request.headers.set(name, value);
    }
    return request;
  },
  onResponse({ response, schemaPath }) {
    handleSessionExpiry(response.status, schemaPath);
  },
};

const client = createClient<paths>({ baseUrl: BASE });
client.use(sessionMiddleware);

type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

function unwrap<T>({ data, error, response }: ApiResult<T>): T {
  if (error !== undefined || !response.ok) {
    throw new ApiError(response.status, errorMessage(error, response.statusText));
  }
  if (data === undefined) throw new ApiError(response.status, "API returned no response body");
  return data;
}

function errorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object") return fallback;
  const detail = "detail" in error ? error.detail : undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? item.msg : undefined))
      .filter((item): item is string => typeof item === "string");
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

function handleSessionExpiry(status: number, schemaPath: string) {
  if (status !== 401 || typeof window === "undefined") return;
  if (schemaPath.startsWith("/auth/")) return;
  if (!localStorage.getItem("pf_token")) return;
  localStorage.removeItem("pf_token");
  if (!window.location.pathname.startsWith("/login")) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
  }
}

const OAUTH_START_PATH = "/auth/oauth/{provider}/start" satisfies keyof paths;

export const api = {
  register: async (email: string, password: string, display_name: string) =>
    unwrap(await client.POST("/auth/register", { body: { email, password, display_name } })),
  login: async (email: string, password: string) =>
    unwrap(await client.POST("/auth/login", { body: { email, password } })),
  me: async () => unwrap(await client.GET("/auth/me")),
  updateMe: async (patch: { display_name?: string; email?: string; avatar?: string }) =>
    unwrap(await client.PATCH("/auth/me", { body: patch })),
  changePassword: async (current_password: string, new_password: string) =>
    unwrap(await client.POST("/auth/change-password", { body: { current_password, new_password } })),
  deleteAccount: async () => unwrap(await client.DELETE("/auth/me")),
  logout: async () => unwrap(await client.POST("/auth/logout")),
  oauthDemo: async (provider: string) =>
    unwrap(await client.POST("/auth/oauth/{provider}/demo", { params: { path: { provider } } })),
  oauthProviders: async () => unwrap(await client.GET("/auth/oauth/providers")),
  oauthStartUrl: (provider: string) =>
    `${BASE}${OAUTH_START_PATH.replace("{provider}", encodeURIComponent(provider))}`,

  games: async (
    q = "",
    tag = "All",
    options: { sort?: string; limit?: number; offset?: number } = {},
  ) =>
    unwrap(
      await client.GET("/games", {
        params: { query: { q, tag, ...options } },
      }),
    ),
  game: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}", { params: { path: { game_id } } })),
  myGames: async () => unwrap(await client.GET("/me/games")),
  myFavorites: async () => unwrap(await client.GET("/me/favorites")),
  preview: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}/preview", { params: { path: { game_id } } })),
  stats: async () => unwrap(await client.GET("/stats")),
  tags: async () => unwrap(await client.GET("/tags")),
  play: async (game_id: string) =>
    unwrap(await client.POST("/games/{game_id}/play", { params: { path: { game_id } } })),
  publish: async (game_id: string) =>
    unwrap(await client.POST("/games/{game_id}/publish", { params: { path: { game_id } } })),
  unpublish: async (game_id: string) =>
    unwrap(await client.POST("/games/{game_id}/unpublish", { params: { path: { game_id } } })),
  gameVersions: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}/versions", { params: { path: { game_id } } })),
  activateVersion: async (game_id: string, version: string) =>
    unwrap(
      await client.POST("/games/{game_id}/versions/{version}/activate", {
        params: { path: { game_id, version } },
      }),
    ),
  updateGame: async (game_id: string, body: { title?: string; summary?: string; tags?: string[] }) =>
    unwrap(await client.PATCH("/games/{game_id}", { params: { path: { game_id } }, body })),
  deleteGame: async (game_id: string) =>
    unwrap(await client.DELETE("/games/{game_id}", { params: { path: { game_id } } })),
  like: async (game_id: string) =>
    unwrap(await client.POST("/games/{game_id}/like", { params: { path: { game_id } } })),
  unlike: async (game_id: string) =>
    unwrap(await client.DELETE("/games/{game_id}/like", { params: { path: { game_id } } })),
  favorite: async (game_id: string) =>
    unwrap(await client.POST("/games/{game_id}/favorite", { params: { path: { game_id } } })),
  unfavorite: async (game_id: string) =>
    unwrap(await client.DELETE("/games/{game_id}/favorite", { params: { path: { game_id } } })),

  userProfile: async (user_id: string) =>
    unwrap(await client.GET("/users/{user_id}", { params: { path: { user_id } } })),
  userGames: async (user_id: string) =>
    unwrap(await client.GET("/users/{user_id}/games", { params: { path: { user_id } } })),
  followUser: async (user_id: string) =>
    unwrap(await client.POST("/users/{user_id}/follow", { params: { path: { user_id } } })),
  unfollowUser: async (user_id: string) =>
    unwrap(await client.DELETE("/users/{user_id}/follow", { params: { path: { user_id } } })),
  comments: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}/comments", { params: { path: { game_id } } })),
  addComment: async (game_id: string, body: string) =>
    unwrap(
      await client.POST("/games/{game_id}/comments", {
        params: { path: { game_id } },
        body: { body },
      }),
    ),
  deleteComment: async (game_id: string, comment_id: string) =>
    unwrap(
      await client.DELETE("/games/{game_id}/comments/{comment_id}", {
        params: { path: { game_id, comment_id } },
      }),
    ),
  relatedGames: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}/related", { params: { path: { game_id } } })),
  leaderboard: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}/leaderboard", { params: { path: { game_id } } })),
  submitScore: async (game_id: string, points: number, player_name?: string) =>
    unwrap(
      await client.POST("/games/{game_id}/score", {
        params: { path: { game_id } },
        body: { points, player_name },
      }),
    ),
  gameManifest: async (game_id: string) =>
    unwrap(await client.GET("/games/{game_id}/manifest", { params: { path: { game_id } } })),
  gameManifestVersion: async (game_id: string, version: string) =>
    unwrap(
      await client.GET("/games/{game_id}/manifest", {
        params: { path: { game_id }, query: { version } },
      }),
    ),

  upload: async (files: FileList | File[]) => {
    const selected = Array.from(files);
    return unwrap(
      await client.POST("/uploads", {
        body: { files: selected as unknown as string[] },
        bodySerializer() {
          const form = new FormData();
          selected.forEach((file) => form.append("files", file));
          return form;
        },
      }),
    );
  },
  createTask: async (
    idea: string,
    asset_ids: string[],
    dimension: "2d" | "3d" = "2d",
    options: { task_kind?: "generation" | "remix"; source_game_id?: string } = {},
  ) =>
    unwrap(
      await client.POST("/tasks", {
        body: { idea, asset_ids, dimension, task_kind: options.task_kind ?? "generation", ...options },
      }),
    ),
  tasks: async () => unwrap(await client.GET("/tasks")),
  task: async (task_id: string) =>
    unwrap(await client.GET("/tasks/{task_id}", { params: { path: { task_id } } })),
  retryTask: async (task_id: string) =>
    unwrap(await client.POST("/tasks/{task_id}/retry", { params: { path: { task_id } } })),
  reviseTask: async (task_id: string, feedback: string) =>
    unwrap(
      await client.POST("/tasks/{task_id}/revise", {
        params: { path: { task_id } },
        body: { feedback },
      }),
    ),
  cancelTask: async (task_id: string) =>
    unwrap(await client.POST("/tasks/{task_id}/cancel", { params: { path: { task_id } } })),
  deleteTask: async (task_id: string) =>
    unwrap(await client.DELETE("/tasks/{task_id}", { params: { path: { task_id } } })),

  memories: async (
    params: { scope_type?: string; scope_id?: string; category?: string; status?: string } = {},
  ) => unwrap(await client.GET("/memory", { params: { query: params } })),
  createMemory: async (body: {
    scope_type: "user" | "game" | "task";
    scope_id?: string | null;
    category: components["schemas"]["MemoryCreateIn"]["category"];
    raw_text: string;
    extracted_text?: string | null;
    importance?: number;
    pinned?: boolean;
  }) =>
    unwrap(
      await client.POST("/memory", {
        body: {
          importance: body.importance ?? 3,
          pinned: body.pinned ?? false,
          ...body,
        },
      }),
    ),
  updateMemory: async (
    memory_id: string,
    body: components["schemas"]["MemoryUpdateIn"],
  ) =>
    unwrap(
      await client.PATCH("/memory/{memory_id}", {
        params: { path: { memory_id } },
        body,
      }),
    ),
  deleteMemory: async (memory_id: string) =>
    unwrap(await client.DELETE("/memory/{memory_id}", { params: { path: { memory_id } } })),
  memorySettings: async () => unwrap(await client.GET("/memory/settings")),
  updateMemorySettings: async (body: components["schemas"]["MemorySettingsIn"]) =>
    unwrap(await client.PATCH("/memory/settings", { body })),
  memoryProfiles: async (
    params: { status?: string; scope_type?: string; scope_id?: string } = {},
  ) => unwrap(await client.GET("/memory/profiles", { params: { query: params } })),
  memoryProfileHistory: async (profile_id: string) =>
    unwrap(
      await client.GET("/memory/profiles/{profile_id}/history", {
        params: { path: { profile_id } },
      }),
    ),
  updateMemoryProfile: async (
    profile_id: string,
    body: { value_text?: string; summary_text?: string },
  ) =>
    unwrap(
      await client.PATCH("/memory/profiles/{profile_id}", {
        params: { path: { profile_id } },
        body,
      }),
    ),
};
