import { test, expect } from "@playwright/test";
import { ExecutionClient, readSubmissions, SUBMISSION_STORAGE, PENDING_TTL } from "../src/app/execution-client";

class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() { return this.data.size; }
  clear() { this.data.clear(); }
  getItem(key: string) { return this.data.get(key) ?? null; }
  key(index: number) { return [...this.data.keys()][index] ?? null; }
  removeItem(key: string) { this.data.delete(key); }
  setItem(key: string, value: string) { this.data.set(key, value); }
}
const path = "/api/workflows/execute";
const id = "11111111-1111-4111-8111-111111111111";
const taskId = "22222222-2222-4222-8222-222222222222";
const row = (state = "completed") => ({ execution_id: id, state, task_id: taskId, workflow_run_id: null, agent_execution_id: null });
const json = (body: unknown, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
let storage: MemoryStorage;
test.beforeEach(() => {
  storage = new MemoryStorage();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { sessionStorage: storage, dispatchEvent: () => true } });
});

test("rapid double submission shares the same request promise and secure key", async () => {
  let posts = 0;
  globalThis.fetch = async (_url, init) => { posts++; expect(new Headers(init?.headers).get("Idempotency-Key")).toMatch(/^[a-f0-9-]{36}$/); return json({ status: "completed", report: "saved" }); };
  const client = new ExecutionClient(path);
  client.initialize();
  const first = client.submit("Private task");
  expect(client.submit("Private task")).toBe(first);
  await first;
  expect(posts).toBe(1);
  expect(storage.getItem(SUBMISSION_STORAGE)).not.toContain("Private task");
});

test("network failure and refresh reuse identity without storing task or credentials", async () => {
  const keys: string[] = [];
  storage.setItem("agentflow_api_token", "offline-auth-token");
  globalThis.fetch = async (_url, init) => { keys.push(new Headers(init?.headers).get("Idempotency-Key")!); throw new TypeError("Network disconnected"); };
  const first = new ExecutionClient(path); first.initialize();
  await first.submit("Sensitive prompt");
  const saved = storage.getItem(SUBMISSION_STORAGE)!;
  expect(saved).not.toContain("Sensitive prompt"); expect(saved).not.toContain("offline-auth-token");
  const refreshed = new ExecutionClient(path); refreshed.initialize();
  globalThis.fetch = async (url, init) => {
    if (String(url).includes("/api/executions/")) return json({ detail: "Execution not found" }, 404);
    keys.push(new Headers(init?.headers).get("Idempotency-Key")!);
    return json({ status: "completed", report: "saved" });
  };
  await refreshed.submit("Sensitive prompt");
  expect(keys).toHaveLength(2); expect(keys[1]).toBe(keys[0]);
});

test("ambiguous legacy-mode failure is never blindly retried", async () => {
  let posts = 0;
  globalThis.fetch = async (_url, init) => {
    if (init?.method === "POST") { posts++; throw new TypeError("Network lost"); }
    return json({ detail: "Durable execution is disabled" }, 503);
  };
  const client = new ExecutionClient(path); client.initialize();
  await client.submit("Offline task"); await client.submit("Offline task");
  expect(posts).toBe(1);
  expect(client.getSnapshot().error).toContain("cannot confirm durable retry protection");
});

test("202 and restored identity monitor by GET only and preserve partial results", async () => {
  const calls: string[] = [];
  globalThis.fetch = async (url, init) => {
    calls.push(init?.method ?? "GET");
    if (init?.method === "POST") return json(row(), 202);
    if (String(url).includes("/api/executions/")) return json(row());
    return json({ id: taskId, status: "completed", result: { report: "Saved report" }, stages: [] });
  };
  const client = new ExecutionClient(path, 0, 3); client.initialize();
  await client.submit("Offline task");
  expect(client.getSnapshot().data?.report).toBe("Saved report");
  const restored = new ExecutionClient(path, 0, 3); restored.initialize();
  await restored.check();
  expect(calls.filter(method => method === "POST")).toHaveLength(1);
  expect(restored.getSnapshot().state).toBe("completed");
});

for (const status of [401, 409, 429, 503, 504]) {
  test(`HTTP ${status} preserves key and safe server message without automatic POST retry`, async () => {
    let posts = 0;
    storage.setItem("agentflow_api_token", "offline-auth-token");
    globalThis.fetch = async () => { posts++; return json({ detail: `Safe failure ${status}` }, status); };
    const client = new ExecutionClient(path); client.initialize();
    await client.submit("Offline task");
    expect(posts).toBe(1); expect(client.getSnapshot().submission?.key).toBeTruthy();
    expect(client.getSnapshot().error).toBe(`Safe failure ${status}`);
    if (status === 401) expect(storage.getItem("agentflow_api_token")).toBeNull();
    if (status === 409) expect(client.getSnapshot().state).toBe("conflict");
    if (status === 504) expect(client.getSnapshot().state).toBe("timed_out");
  });
}

test("interrupted execution shows committed output and never starts a new request", async () => {
  let posts = 0;
  globalThis.fetch = async (url, init) => {
    if (init?.method === "POST") { posts++; return json(row("interrupted"), 202); }
    if (String(url).includes("/api/executions/")) return json(row("interrupted"));
    return json({ id: taskId, status: "interrupted", result: { research: "Committed partial output", total_tokens: 5 }, stages: [] });
  };
  const client = new ExecutionClient(path, 0, 3); client.initialize();
  await client.submit("Offline task"); await client.submit("Offline task");
  expect(posts).toBe(1); expect(client.getSnapshot().state).toBe("interrupted");
  expect(client.getSnapshot().data?.total_tokens).toBe(5);
});

test("polling is bounded and check-status never sends a POST", async () => {
  let posts = 0, reads = 0;
  globalThis.fetch = async (url, init) => {
    if (init?.method === "POST") { posts++; return json(row("running"), 202); }
    if (String(url).includes("/api/executions/")) { reads++; return json(row("running")); }
    return json({ id: taskId, status: "running", result: { plan: "Partial" }, stages: [] });
  };
  const client = new ExecutionClient(path, 0, 3); client.initialize();
  await client.submit("Offline task"); expect(reads).toBe(3); expect(client.getSnapshot().state).toBe("paused");
  await client.check(); expect(reads).toBe(6); expect(posts).toBe(1);
});

test("only explicit new intent replaces a key; edited retry fails closed", async () => {
  const keys: string[] = [];
  globalThis.fetch = async (_url, init) => { keys.push(new Headers(init?.headers).get("Idempotency-Key")!); return json({ status: "completed" }); };
  const client = new ExecutionClient(path); client.initialize();
  await client.submit("Original task"); await client.submit("Edited task");
  expect(keys).toHaveLength(1); expect(client.getSnapshot().state).toBe("conflict");
  client.newIntent(); await client.submit("Edited task");
  expect(keys).toHaveLength(2); expect(keys[0]).not.toBe(keys[1]);
});

test("expiry removes old keys but retains a recovery marker and completed metadata is cleaned", () => {
  const now = Date.now();
  storage.setItem(SUBMISSION_STORAGE, JSON.stringify({
    [path]: { path, key: crypto.randomUUID(), state: "unknown", createdAt: now - PENDING_TTL - 1, updatedAt: now, attempted: true },
    "/api/workflows/stream": { path: "/api/workflows/stream", key: crypto.randomUUID(), state: "completed", createdAt: 0, updatedAt: 0, attempted: true },
  }));
  const records = readSubmissions(storage, now);
  expect(records[path].key).toBeUndefined(); expect(records[path].state).toBe("expired");
  expect(records["/api/workflows/stream"]).toBeUndefined();
});

test("storage unavailability fails closed before any paid submission", async () => {
  let posts = 0;
  globalThis.fetch = async () => { posts++; return json({ status: "completed" }); };
  storage.setItem = () => { throw new Error("Browser storage unavailable"); };
  const client = new ExecutionClient(path); client.initialize(); await client.submit("Offline task");
  expect(posts).toBe(0); expect(client.getSnapshot().error).toContain("storage unavailable");
});
