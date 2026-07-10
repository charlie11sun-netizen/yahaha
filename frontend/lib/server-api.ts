import "server-only";

import createClient, { type Middleware } from "openapi-fetch";
import { cache } from "react";

import type { paths } from "./api-types";
import { gateToken, sitePassword } from "./gate";

const SERVER_BASE = (
  process.env.API_INTERNAL_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8000"
).replace(/\/+$/, "");

export class ServerApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const gateMiddleware: Middleware = {
  async onRequest({ request }) {
    const password = sitePassword();
    if (password) request.headers.set("X-Gate-Token", await gateToken(password));
    return request;
  },
};

const serverClient = createClient<paths>({ baseUrl: SERVER_BASE, cache: "no-store" });
serverClient.use(gateMiddleware);

type ApiResult<T> = { data?: T; error?: unknown; response: Response };

function unwrap<T>({ data, error, response }: ApiResult<T>): T {
  if (error !== undefined || !response.ok) {
    throw new ServerApiError(response.status, errorMessage(error, response.statusText));
  }
  if (data === undefined) {
    throw new ServerApiError(response.status, "API returned no response body");
  }
  return data;
}

function errorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object" || !("detail" in error)) return fallback;
  return typeof error.detail === "string" ? error.detail : fallback;
}

export async function getPublicGames(
  q = "",
  tag = "All",
  options: { sort?: string; limit?: number; offset?: number } = {},
) {
  return unwrap(
    await serverClient.GET("/games", {
      params: { query: { q, tag, ...options } },
    }),
  );
}

export const getPublicTags = cache(async () => unwrap(await serverClient.GET("/tags")));
export const getPublicGame = cache(async (game_id: string) =>
  unwrap(await serverClient.GET("/games/{game_id}", { params: { path: { game_id } } })),
);
export const getPublicGameComments = cache(async (game_id: string) =>
  unwrap(
    await serverClient.GET("/games/{game_id}/comments", {
      params: { path: { game_id } },
    }),
  ),
);
export const getPublicRelatedGames = cache(async (game_id: string) =>
  unwrap(
    await serverClient.GET("/games/{game_id}/related", {
      params: { path: { game_id } },
    }),
  ),
);
export const getPublicGameManifest = cache(async (game_id: string) =>
  unwrap(
    await serverClient.GET("/games/{game_id}/manifest", {
      params: { path: { game_id } },
    }),
  ),
);
export const getPublicLeaderboard = cache(async (game_id: string) =>
  unwrap(
    await serverClient.GET("/games/{game_id}/leaderboard", {
      params: { path: { game_id } },
    }),
  ),
);
export const getPublicUserProfile = cache(async (user_id: string) =>
  unwrap(await serverClient.GET("/users/{user_id}", { params: { path: { user_id } } })),
);
export const getPublicUserGames = cache(async (user_id: string) =>
  unwrap(
    await serverClient.GET("/users/{user_id}/games", {
      params: { path: { user_id } },
    }),
  ),
);
