/** Sandboxed, host-backed persistence for saves, settings, and key bindings.
 * Generated games must not access browser storage directly. The GameWeave host
 * namespaces values by game id and answers through this postMessage bridge.
 * In the isolated QA sandbox (where no host answers), an in-memory fallback keeps
 * the game playable and load() resolves quickly instead of hanging startup. */

type StoredValue = unknown;

type StorageResponse = {
  type: "gameweave:storage:response";
  requestId: string;
  ok: boolean;
  found?: boolean;
  value?: StoredValue;
  error?: string;
};

type CloneResult<T> = { ok: true; value: T } | { ok: false };

export class GameWeaveBridge {
  private static readonly memory = new Map<string, StoredValue>();
  private static sequence = 0;

  private static safeSlot(slot: string): string {
    const normalized = String(slot || "default").replace(/[^A-Za-z0-9_.-]/g, "-").slice(0, 64);
    return normalized || "default";
  }

  /** JSON-only values keep host persistence deterministic and give the memory
   * fallback value semantics: callers never share an object reference with the
   * cached copy. The byte check mirrors the host's per-slot limit. */
  private static clone<T>(value: T): CloneResult<T> {
    const ancestors = new Set<object>();
    const isJsonValue = (candidate: unknown): boolean => {
      if (candidate === null || typeof candidate === "string" || typeof candidate === "boolean") return true;
      if (typeof candidate === "number") return Number.isFinite(candidate);
      if (typeof candidate !== "object" || ancestors.has(candidate)) return false;
      const prototype = Object.getPrototypeOf(candidate);
      if (!Array.isArray(candidate) && prototype !== Object.prototype && prototype !== null) return false;
      if (Object.getOwnPropertySymbols(candidate).length > 0) return false;
      ancestors.add(candidate);
      try {
        if (Array.isArray(candidate)) {
          for (let index = 0; index < candidate.length; index += 1) {
            if (!(index in candidate) || !isJsonValue(candidate[index])) return false;
          }
        } else {
          for (const key of Object.keys(candidate)) {
            if (!isJsonValue((candidate as Record<string, unknown>)[key])) return false;
          }
        }
        return true;
      } finally {
        ancestors.delete(candidate);
      }
    };
    try {
      if (!isJsonValue(value)) return { ok: false };
      const encoded = JSON.stringify(value);
      if (typeof encoded !== "string" || new TextEncoder().encode(encoded).byteLength > 64 * 1024) {
        return { ok: false };
      }
      return { ok: true, value: JSON.parse(encoded) as T };
    } catch {
      return { ok: false };
    }
  }

  static save(slot: string, value: StoredValue, timeoutMs = 250): Promise<boolean> {
    const key = GameWeaveBridge.safeSlot(slot);
    const cloned = GameWeaveBridge.clone(value);
    if (!cloned.ok) return Promise.resolve(false);
    const hadPrevious = GameWeaveBridge.memory.has(key);
    const previous = GameWeaveBridge.memory.get(key);
    GameWeaveBridge.memory.set(key, cloned.value);
    const requestId = `gw-storage-${Date.now()}-${++GameWeaveBridge.sequence}`;
    return new Promise<boolean>((resolve) => {
      let settled = false;
      let timer = 0;
      const finish = (ok: boolean, rollback = false): void => {
        if (settled) return;
        settled = true;
        window.removeEventListener("message", onMessage);
        window.clearTimeout(timer);
        if (rollback) {
          if (hadPrevious) GameWeaveBridge.memory.set(key, previous);
          else GameWeaveBridge.memory.delete(key);
        }
        resolve(ok);
      };
      const onMessage = (event: MessageEvent<StorageResponse>): void => {
        if (event.source !== window.parent) return;
        const data = event.data;
        if (!data || data.type !== "gameweave:storage:response" || data.requestId !== requestId) return;
        finish(data.ok, !data.ok);
      };
      // Keep the in-memory copy for a hostless QA sandbox, but do not claim
      // durable persistence unless the host explicitly acknowledges the write.
      timer = window.setTimeout(() => finish(false), Math.max(50, timeoutMs));
      window.addEventListener("message", onMessage);
      try {
        window.parent.postMessage({ type: "gameweave:storage:set", key, value: cloned.value, requestId }, "*");
      } catch {
        finish(false, true);
      }
    });
  }

  static load<T>(slot: string, fallback: T, timeoutMs = 250): Promise<T> {
    const key = GameWeaveBridge.safeSlot(slot);
    const clonedFallback = GameWeaveBridge.clone(fallback);
    const safeFallback = clonedFallback.ok ? clonedFallback.value : fallback;
    const memoryValue = GameWeaveBridge.memory.has(key) ? GameWeaveBridge.memory.get(key) : safeFallback;
    const clonedMemory = GameWeaveBridge.clone(memoryValue as T);
    const memoryFallback = clonedMemory.ok ? clonedMemory.value : safeFallback;
    const requestId = `gw-storage-${Date.now()}-${++GameWeaveBridge.sequence}`;
    return new Promise<T>((resolve) => {
      let settled = false;
      let timer = 0;
      const finish = (value: T): void => {
        if (settled) return;
        settled = true;
        window.removeEventListener("message", onMessage);
        window.clearTimeout(timer);
        resolve(value);
      };
      const onMessage = (event: MessageEvent<StorageResponse>): void => {
        if (event.source !== window.parent) return;
        const data = event.data;
        if (!data || data.type !== "gameweave:storage:response" || data.requestId !== requestId) return;
        if (data.ok && data.found) {
          const remote = GameWeaveBridge.clone(data.value as T);
          if (!remote.ok) return finish(memoryFallback);
          const cached = GameWeaveBridge.clone(remote.value);
          if (cached.ok) GameWeaveBridge.memory.set(key, cached.value);
          finish(remote.value);
        } else if (data.ok) {
          GameWeaveBridge.memory.delete(key);
          const freshFallback = GameWeaveBridge.clone(fallback);
          finish(freshFallback.ok ? freshFallback.value : fallback);
        } else {
          finish(memoryFallback);
        }
      };
      timer = window.setTimeout(() => finish(memoryFallback), Math.max(50, timeoutMs));
      window.addEventListener("message", onMessage);
      try {
        window.parent.postMessage({ type: "gameweave:storage:get", key, requestId }, "*");
      } catch {
        finish(memoryFallback);
      }
    });
  }
}
