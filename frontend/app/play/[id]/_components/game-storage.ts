export const GAME_STORAGE_MAX_SLOTS = 32;
export const GAME_STORAGE_MAX_ITEM_BYTES = 64 * 1024;
export const GAME_STORAGE_MAX_TOTAL_BYTES = 256 * 1024;

const SLOT_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;
const REQUEST_ID_PATTERN = /^[A-Za-z0-9_.:-]{1,120}$/;

export interface StorageLike {
  readonly length: number;
  key(index: number): string | null;
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export type GameStorageResponse = {
  type: "gameweave:storage:response";
  requestId: string;
  ok: boolean;
  found?: boolean;
  value?: unknown;
  error?:
    | "invalid_key"
    | "unserializable"
    | "item_too_large"
    | "slot_limit"
    | "game_quota"
    | "storage_unavailable"
    | "corrupt_value";
};

type GameStorageRequest = {
  type: "gameweave:storage:get" | "gameweave:storage:set";
  requestId: string;
  key?: unknown;
  value?: unknown;
};

function response(
  requestId: string,
  result: Omit<GameStorageResponse, "type" | "requestId">,
): GameStorageResponse {
  return { type: "gameweave:storage:response", requestId, ...result };
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function isJsonValue(value: unknown, ancestors = new Set<object>()): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "object") return false;
  if (ancestors.has(value)) return false;

  const prototype = Object.getPrototypeOf(value);
  if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) return false;
  if (Object.getOwnPropertySymbols(value).length > 0) return false;

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index += 1) {
        if (!(index in value) || !isJsonValue(value[index], ancestors)) return false;
      }
      return true;
    }
    for (const key of Object.keys(value)) {
      if (!isJsonValue((value as Record<string, unknown>)[key], ancestors)) return false;
    }
    return true;
  } finally {
    ancestors.delete(value);
  }
}

function encodeValue(value: unknown): { encoded: string; bytes: number } | null {
  try {
    if (!isJsonValue(value)) return null;
    const encoded = JSON.stringify(value);
    if (typeof encoded !== "string") return null;
    return { encoded, bytes: utf8Bytes(encoded) };
  } catch {
    return null;
  }
}

function requestFrom(value: unknown): GameStorageRequest | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<GameStorageRequest>;
  if (candidate.type !== "gameweave:storage:get" && candidate.type !== "gameweave:storage:set") return null;
  if (typeof candidate.requestId !== "string" || !REQUEST_ID_PATTERN.test(candidate.requestId)) return null;
  return candidate as GameStorageRequest;
}

export function gameStoragePrefix(gameId: string): string {
  return `gameweave:game-storage:${encodeURIComponent(gameId)}:`;
}

/**
 * Apply one authenticated iframe request to host storage. Authentication is
 * intentionally handled by the caller with MessageEvent.source because an
 * opaque-origin sandbox reports origin="null".
 */
export function handleGameStorageRequest(
  storage: StorageLike,
  gameId: string,
  rawRequest: unknown,
): GameStorageResponse | null {
  const request = requestFrom(rawRequest);
  if (!request) return null;
  if (typeof request.key !== "string" || !SLOT_PATTERN.test(request.key)) {
    return response(request.requestId, { ok: false, error: "invalid_key" });
  }

  const prefix = gameStoragePrefix(gameId);
  const storageKey = `${prefix}${request.key}`;
  try {
    if (request.type === "gameweave:storage:get") {
      const encoded = storage.getItem(storageKey);
      if (encoded === null) return response(request.requestId, { ok: true, found: false });
      if (utf8Bytes(encoded) > GAME_STORAGE_MAX_ITEM_BYTES) {
        return response(request.requestId, { ok: false, error: "item_too_large" });
      }
      try {
        const value: unknown = JSON.parse(encoded);
        if (!isJsonValue(value)) return response(request.requestId, { ok: false, error: "corrupt_value" });
        return response(request.requestId, { ok: true, found: true, value });
      } catch {
        return response(request.requestId, { ok: false, error: "corrupt_value" });
      }
    }

    const serialized = encodeValue(request.value);
    if (!serialized) return response(request.requestId, { ok: false, error: "unserializable" });
    if (serialized.bytes > GAME_STORAGE_MAX_ITEM_BYTES) {
      return response(request.requestId, { ok: false, error: "item_too_large" });
    }

    const entries = new Map<string, number>();
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (!key?.startsWith(prefix)) continue;
      const encoded = storage.getItem(key);
      if (encoded !== null) entries.set(key, utf8Bytes(encoded));
    }

    const previousBytes = entries.get(storageKey) ?? 0;
    if (!entries.has(storageKey) && entries.size >= GAME_STORAGE_MAX_SLOTS) {
      return response(request.requestId, { ok: false, error: "slot_limit" });
    }
    const nextTotal = [...entries.values()].reduce((total, bytes) => total + bytes, 0)
      - previousBytes
      + serialized.bytes;
    if (nextTotal > GAME_STORAGE_MAX_TOTAL_BYTES) {
      return response(request.requestId, { ok: false, error: "game_quota" });
    }

    storage.setItem(storageKey, serialized.encoded);
    return response(request.requestId, { ok: true });
  } catch {
    return response(request.requestId, { ok: false, error: "storage_unavailable" });
  }
}
