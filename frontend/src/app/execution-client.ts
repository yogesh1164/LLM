import { apiFetch } from "./api";

export type ExecutionState = "idle" | "pending" | "running" | "completed" | "failed" | "timed_out" | "interrupted" | "unknown" | "conflict" | "paused" | "expired";
export type Submission = { key?: string; executionId?: string; path: string; state: ExecutionState; createdAt: number; updatedAt: number; attempted: boolean };
export type ExecutionSnapshot = { submission: Submission | null; state: ExecutionState; busy: boolean; error: string; data: Record<string, unknown> | null };
type Journal = { execution_id: string; state: "running" | "completed" | "failed" | "interrupted"; task_id: string | null; workflow_run_id: string | null; agent_execution_id: string | null };
export type ExecutionEvent = Record<string, unknown> & { type: string };
export const SUBMISSION_STORAGE = "agentflow.executions.v1";
export const PENDING_TTL = 7 * 24 * 60 * 60 * 1000;
const COMPLETED_TTL = 24 * 60 * 60 * 1000;
const MAX_SUBMISSIONS = 24;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PATH = /^\/api\/(workflows\/(execute|collaborate|stream)|agents\/[0-9a-f-]{36}\/execute|custom-workflows\/[0-9a-f-]{36}\/execute)$/;
const states: ExecutionState[] = ["idle", "pending", "running", "completed", "failed", "timed_out", "interrupted", "unknown", "conflict", "paused", "expired"];
export const EMPTY_EXECUTION: ExecutionSnapshot = { submission: null, state: "idle", busy: false, error: "", data: null };

export function readSubmissions(storage: Storage, now = Date.now()): Record<string, Submission> {
  const raw = storage.getItem(SUBMISSION_STORAGE);
  if (!raw) return {};
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { throw new Error("Saved submission identity is unreadable. Review execution history before starting new work."); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid saved submission identity. Review execution history.");
  const records: Record<string, Submission> = {};
  for (const [path, item] of Object.entries(parsed)) {
    if (!PATH.test(path) || !item || typeof item !== "object") throw new Error("Invalid saved submission identity. Review execution history.");
    const record = item as Submission;
    if (!states.includes(record.state) || !Number.isFinite(record.createdAt) || !Number.isFinite(record.updatedAt)
        || record.createdAt > now + 60_000 || (record.key !== undefined && !UUID.test(record.key))
        || (record.executionId !== undefined && !UUID.test(record.executionId))) throw new Error("Invalid saved submission identity. Review execution history.");
    if (record.state === "completed" && now - record.updatedAt > COMPLETED_TTL) continue;
    const expired = now - record.createdAt > PENDING_TTL;
    // No task, fingerprint, bearer token, raw errors or result content is persisted.
    records[path] = { path, key: expired ? undefined : record.key, executionId: record.executionId,
      state: expired && record.state !== "completed" ? "expired" : record.state, createdAt: record.createdAt, updatedAt: record.updatedAt, attempted: record.attempted === true };
  }
  if (Object.keys(records).length > MAX_SUBMISSIONS) throw new Error("Too many saved submissions. Review execution history before starting new work.");
  storage.setItem(SUBMISSION_STORAGE, JSON.stringify(records));
  return records;
}

function save(record: Submission): Submission {
  if (Date.now() - record.createdAt > PENDING_TTL) record = { ...record, key: undefined, state: record.state === "completed" ? "completed" : "expired" };
  const records = readSubmissions(window.sessionStorage);
  if (!records[record.path] && Object.keys(records).length >= MAX_SUBMISSIONS) throw new Error("Saved submission limit reached. Review and clear an existing submission first.");
  records[record.path] = record;
  window.sessionStorage.setItem(SUBMISSION_STORAGE, JSON.stringify(records));
  return record;
}

class ExecutionError extends Error {
  constructor(message: string, readonly status = 0) { super(message); }
}

async function checked(response: Response): Promise<Response> {
  if (response.ok) return response;
  const fallback: Record<number, string> = { 401: "Authentication required. Reconnect to inspect this submission.",
    429: "Rate limit exceeded. Wait before checking this submission again.", 503: "Service unavailable. The existing submission may still have run.",
    504: "Execution timed out. Inspect saved history before starting new work." };
  let message = fallback[response.status] ?? `Request failed (${response.status}).`;
  try { const body = await response.json(); if (typeof body.detail === "string") message = body.detail; } catch { /* Keep the safe HTTP fallback. */ }
  throw new ExecutionError(message, response.status);
}

function journal(value: unknown): Journal {
  const row = value as Journal;
  if (!row || !UUID.test(row.execution_id) || !["running", "completed", "failed", "interrupted"].includes(row.state)) throw new Error("Invalid execution status response. Check saved history.");
  for (const id of [row.task_id, row.workflow_run_id, row.agent_execution_id]) if (id != null && !UUID.test(id)) throw new Error("Invalid execution result identifier.");
  return row;
}

function targetState(data: Record<string, unknown>, fallback: ExecutionState): ExecutionState {
  if (data.status === "cancelled") return "interrupted";
  if (states.includes(data.status as ExecutionState)) {
    if (data.status === "failed" && Array.isArray(data.stages) && data.stages.some(s => s.status === "timed_out")) return "timed_out";
    return data.status as ExecutionState;
  }
  return fallback;
}

export class ExecutionClient {
  private view = EMPTY_EXECUTION;
  private listeners = new Set<() => void>();
  private active: Promise<Record<string, unknown> | null> | null = null;
  private abort: AbortController | null = null;
  private task: string | null = null; // Memory only; never browser storage.
  private generation = 0;
  constructor(readonly path: string, private readonly pollMs = 5000, private readonly maxPolls = 180) {}
  getSnapshot = () => this.view;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  private publish(change: Partial<ExecutionSnapshot>) { this.view = { ...this.view, ...change }; this.listeners.forEach(listener => listener()); }
  private record(change: Partial<Submission>) {
    const current = this.view.submission;
    if (!current) throw new Error("Submission identity is missing. Inspect execution history.");
    const submission = save({ ...current, ...change, updatedAt: Date.now() });
    this.publish({ submission, state: submission.state });
    return submission;
  }
  initialize() {
    const generation = ++this.generation;
    try {
      const submission = readSubmissions(window.sessionStorage)[this.path] ?? null;
      this.publish({ submission, state: submission?.state ?? "idle" });
      // Restoration is GET-only, including React Strict Mode and browser refresh.
      if (submission?.executionId) {
        if (this.active) void this.active.finally(() => { if (generation === this.generation) void this.check(); });
        else void this.check();
      }
    } catch (error) { this.publish({ state: "expired", error: error instanceof Error ? error.message : "Submission storage is unavailable." }); }
  }
  stop = () => { this.generation++; this.abort?.abort(); };
  clearResult = () => { this.publish({ data: null }); };
  newIntent() {
    if (this.view.busy) return;
    let records: Record<string, Submission>;
    try { records = readSubmissions(window.sessionStorage); } catch { records = {}; }
    delete records[this.path];
    window.sessionStorage.setItem(SUBMISSION_STORAGE, JSON.stringify(records));
    this.task = null;
    this.publish({ ...EMPTY_EXECUTION });
  }
  private run(operation: (signal: AbortSignal) => Promise<Record<string, unknown> | null>) {
    if (this.active) return this.active; // Synchronous lock, before any React rerender.
    this.abort = new AbortController();
    const watchdog = setTimeout(() => this.abort?.abort(), 35 * 60 * 1000);
    this.publish({ busy: true, error: "" });
    this.active = operation(this.abort.signal).catch(error => {
      const status = error instanceof ExecutionError ? error.status : 0;
      const state = status === 409 ? "conflict" : status === 504 ? "timed_out" : "unknown";
      const message = error instanceof Error && error.name !== "AbortError" ? error.message : "Monitoring stopped. Check status; do not start the submission again.";
      if (this.view.submission) { try { this.record({ state }); } catch { /* Do not replace a lost identity or send another request. */ } }
      this.publish({ state, error: message });
      return null;
    }).finally(() => { clearTimeout(watchdog); this.active = null; this.abort = null; this.publish({ busy: false }); });
    return this.active;
  }
  submit(task: string, onEvent?: (event: ExecutionEvent) => void) {
    return this.run(async signal => {
      if (!PATH.test(this.path)) throw new Error("Invalid execution path.");
      let submission = this.view.submission;
      if (submission?.executionId) return this.monitor(signal);
      if (submission && (!submission.key || submission.state === "expired" || submission.state === "conflict")) throw new Error("Review the existing submission before choosing New execution.");
      if (this.task !== null && this.task !== task) throw new ExecutionError("Retry requires the original task. Choose New execution for a different task.", 409);
      if (!submission) {
        submission = { path: this.path, key: crypto.randomUUID(), state: "pending", createdAt: Date.now(), updatedAt: Date.now(), attempted: false };
        save(submission); // Fail closed if durable identity cannot be retained.
        this.publish({ submission, state: "pending", data: null });
      }
      if (submission.attempted) {
        // The working legacy server ignores keys. Never retry an ambiguous legacy call.
        const probe = await apiFetch(`/api/executions/${crypto.randomUUID()}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) });
        const body = await probe.json().catch(() => ({}));
        if (probe.status !== 404 || body.detail !== "Execution not found") {
          if (probe.status === 401 || probe.status === 429) await checked(probe);
          throw new Error("This server cannot confirm durable retry protection. Review execution history before starting new work.");
        }
      }
      this.task = task;
      this.record({ attempted: true, state: "pending" });
      let response: Response;
      try { response = await apiFetch(this.path, { method: "POST", signal,
        headers: { "Content-Type": "application/json", "Idempotency-Key": submission.key! }, body: JSON.stringify({ task }) }); }
      catch (error) {
        if (this.view.submission?.executionId && !signal.aborted) return this.monitor(signal);
        throw error;
      }
      const id = response.headers.get("X-Execution-ID");
      if (id && UUID.test(id)) this.record({ executionId: id });
      if (response.status === 202) {
        const row = journal(await response.json());
        this.record({ executionId: row.execution_id, state: row.state });
        return this.monitor(signal);
      }
      try { await checked(response); } catch (error) {
        if (this.view.submission?.executionId && !signal.aborted && response.status !== 409 && response.status !== 401) {
          this.publish({ error: error instanceof Error ? error.message : "Execution failed." });
          return this.monitor(signal);
        }
        throw error;
      }
      if (response.headers.get("content-type")?.includes("text/event-stream")) return this.consumeStream(response, signal, onEvent);
      const data = await response.json() as Record<string, unknown>;
      this.record({ state: targetState(data, "completed") });
      this.publish({ data });
      return data;
    });
  }
  check = () => this.run(signal => this.monitor(signal));
  private async result(row: Journal, signal: AbortSignal): Promise<Record<string, unknown> | null> {
    let path: string;
    if (row.task_id) path = `/api/tasks/${row.task_id}`;
    else if (row.workflow_run_id) path = `/api/custom-workflows/runs/${row.workflow_run_id}`;
    else if (row.agent_execution_id && this.path.startsWith("/api/agents/")) path = this.path.replace(/\/execute$/, "/executions");
    else return null;
    const response = await apiFetch(path, { signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) });
    if (response.status === 404) return null; // Deleted history never permits resubmission.
    await checked(response);
    const body = await response.json();
    const data = row.agent_execution_id ? body.find((item: { id: string }) => item.id === row.agent_execution_id) : body;
    if (!data) return null;
    return row.task_id ? { ...(data.result ?? {}), task_id: data.id, status: data.status, stages: data.stages, error: data.error } : data;
  }
  private async monitor(signal: AbortSignal) {
    const id = this.view.submission?.executionId;
    if (!id) throw new Error("Server state is unknown. Re-enter the original task and retry the same submission, or inspect history.");
    for (let attempt = 0; attempt < this.maxPolls; attempt++) {
      if (signal.aborted) throw new DOMException("Monitoring stopped", "AbortError");
      const row = journal(await (await checked(await apiFetch(`/api/executions/${id}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) }))).json());
      if (row.execution_id !== id) throw new Error("Execution status identity mismatch.");
      const data = await this.result(row, signal);
      const state = row.state === "running" ? "running" : data ? targetState(data, row.state) : row.state;
      this.record({ state });
      this.publish({ data: data ?? this.view.data });
      if (row.state !== "running") return data;
      await new Promise<void>((resolve, reject) => {
        const aborted = () => { clearTimeout(timer); reject(new DOMException("Monitoring stopped", "AbortError")); };
        const timer = setTimeout(() => { signal.removeEventListener("abort", aborted); resolve(); }, this.pollMs);
        signal.addEventListener("abort", aborted, { once: true });
      });
    }
    this.record({ state: "paused" });
    this.publish({ error: "Monitoring paused after 15 minutes. Check status to continue; no execution was resubmitted." });
    return this.view.data;
  }
  private async consumeStream(response: Response, signal: AbortSignal, onEvent?: (event: ExecutionEvent) => void) {
    if (!response.body) throw new Error("Streaming unavailable. Inspect submission status.");
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "", final: Record<string, unknown> | null = null;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        if (buffer.length > 1_048_576) throw new Error("Streaming event exceeded the client limit.");
        const packets = buffer.split("\n\n"); buffer = packets.pop() ?? "";
        for (const packet of packets) {
          const line = packet.split("\n").find(line => line.startsWith("data: "));
          if (!line) continue;
          const event = JSON.parse(line.slice(6)) as ExecutionEvent;
          onEvent?.(event);
          if (event.type === "started" || event.type === "stage") this.record({ state: "running" });
          if (event.type === "result") { final = { ...event, status: "completed" }; this.publish({ data: final }); }
          if (event.type === "error") {
            const message = typeof event.detail === "string" ? event.detail : "Execution failed. Inspect saved history.";
            if (this.view.submission?.executionId) throw new Error(message);
            this.record({ state: event.status === "timed_out" ? "timed_out" : "failed" });
            this.publish({ error: message });
            await reader.cancel();
            return null;
          }
        }
      }
      if (final) { this.record({ state: "completed" }); return final; }
      throw new Error("Stream ended without a final result. Check the existing submission.");
    } catch (error) {
      await reader.cancel().catch(() => undefined);
      if (this.view.submission?.executionId && !signal.aborted) return this.monitor(signal);
      throw error;
    } finally { reader.releaseLock(); }
  }
}

export const executionLabel = (state: ExecutionState) => ({ idle: "Ready", pending: "Pending", running: "Running", completed: "Completed", failed: "Failed", timed_out: "Timed out",
  interrupted: "Interrupted / recovery required", unknown: "Connection lost / state unknown", conflict: "Conflict / review required", paused: "Monitoring paused", expired: "Recovery required" })[state];
