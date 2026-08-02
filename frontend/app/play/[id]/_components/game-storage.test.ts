import assert from "node:assert/strict";
import test from "node:test";

import {
  GAME_STORAGE_MAX_ITEM_BYTES,
  gameStoragePrefix,
  handleGameStorageRequest,
  type StorageLike,
} from "./game-storage";

class MemoryStorage implements StorageLike {
  readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

const setRequest = (requestId: string, key: string, value: unknown) => ({
  type: "gameweave:storage:set",
  requestId,
  key,
  value,
});

const getRequest = (requestId: string, key: string) => ({
  type: "gameweave:storage:get",
  requestId,
  key,
});

test("stores and loads slots in isolated per-game namespaces", () => {
  const storage = new MemoryStorage();
  assert.equal(handleGameStorageRequest(storage, "game-a", setRequest("set-a", "save", { hp: 4 }))?.ok, true);
  assert.equal(handleGameStorageRequest(storage, "game-b", setRequest("set-b", "save", { hp: 9 }))?.ok, true);

  assert.deepEqual(handleGameStorageRequest(storage, "game-a", getRequest("get-a", "save")), {
    type: "gameweave:storage:response",
    requestId: "get-a",
    ok: true,
    found: true,
    value: { hp: 4 },
  });
  assert.deepEqual(handleGameStorageRequest(storage, "game-b", getRequest("get-b", "save"))?.value, { hp: 9 });
  assert.equal(storage.values.has(`${gameStoragePrefix("game-a")}save`), true);
  assert.equal(storage.values.has(`${gameStoragePrefix("game-b")}save`), true);
});

test("ACKs invalid, lossy, cyclic, and oversized writes with an error", () => {
  const storage = new MemoryStorage();
  const cyclic: { self?: unknown } = {};
  cyclic.self = cyclic;

  assert.equal(handleGameStorageRequest(storage, "g", setRequest("bad-key", "../save", 1))?.error, "invalid_key");
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("undefined", "save", undefined))?.error, "unserializable");
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("function", "save", { bad: () => 1 }))?.error, "unserializable");
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("cyclic", "save", cyclic))?.error, "unserializable");
  assert.equal(
    handleGameStorageRequest(storage, "g", setRequest("large", "save", "x".repeat(GAME_STORAGE_MAX_ITEM_BYTES)))?.error,
    "item_too_large",
  );
  assert.equal(storage.length, 0);
});

test("accepts an item exactly at the 64 KiB serialized boundary", () => {
  const storage = new MemoryStorage();
  const exact = "x".repeat(GAME_STORAGE_MAX_ITEM_BYTES - 2); // JSON adds two quote bytes.
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("exact", "save", exact))?.ok, true);
  assert.equal(new TextEncoder().encode(storage.getItem(`${gameStoragePrefix("g")}save`) ?? "").byteLength, GAME_STORAGE_MAX_ITEM_BYTES);
});

test("enforces 32 slots while allowing updates to an existing slot", () => {
  const storage = new MemoryStorage();
  for (let index = 0; index < 32; index += 1) {
    assert.equal(
      handleGameStorageRequest(storage, "g", setRequest(`set-${index}`, `slot-${index}`, index))?.ok,
      true,
    );
  }
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("overflow", "slot-32", 32))?.error, "slot_limit");
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("update", "slot-0", { changed: true }))?.ok, true);
  assert.equal(storage.length, 32);
});

test("enforces the aggregate quota independently for each game", () => {
  const storage = new MemoryStorage();
  const chunk = "x".repeat(60 * 1024);
  for (let index = 0; index < 4; index += 1) {
    assert.equal(handleGameStorageRequest(storage, "g", setRequest(`chunk-${index}`, `slot-${index}`, chunk))?.ok, true);
  }
  assert.equal(handleGameStorageRequest(storage, "g", setRequest("quota", "slot-4", chunk))?.error, "game_quota");
  assert.equal(handleGameStorageRequest(storage, "other", setRequest("other", "slot-4", chunk))?.ok, true);
});

test("missing and corrupt slots return explicit responses", () => {
  const storage = new MemoryStorage();
  assert.deepEqual(handleGameStorageRequest(storage, "g", getRequest("missing", "save")), {
    type: "gameweave:storage:response",
    requestId: "missing",
    ok: true,
    found: false,
  });
  storage.values.set(`${gameStoragePrefix("g")}save`, "{");
  assert.equal(handleGameStorageRequest(storage, "g", getRequest("corrupt", "save"))?.error, "corrupt_value");
});
