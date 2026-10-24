import { test, expect, type Page, type Route } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111", taskId = "22222222-2222-4222-8222-222222222222";
const agentId = "33333333-3333-4333-8333-333333333333", workflowId = "44444444-4444-4444-8444-444444444444";
const dashboard = { agents: 5, provider: "gemini", model: "gemini-3.5-flash-lite", web_search_enabled: false, completed: 0, failed: 0, workflows: 0, token_usage: 0, estimated_cost: null, history: [] };
const descriptor = (state: string) => ({ execution_id: id, state, task_id: taskId, workflow_run_id: null, agent_execution_id: null });
const result = (status = "completed") => ({ id: taskId, status, result: { report: "Saved report", research: "Saved research", total_tokens: 5 }, stages: [{ agent: "Research", status: "completed", output: "Saved research", input_tokens: 3, output_tokens: 2 }] });
const fulfill = (route: Route, json: unknown, status = 200) => route.fulfill({ status, json });

async function setup(page: Page, handle?: (route: Route, path: string) => Promise<void>) {
  await page.addInitScript(() => { if (!sessionStorage.getItem("agentflow_api_token")) sessionStorage.setItem("agentflow_api_token", "offline-browser-test-token"); });
  // Every API request is intercepted. No real provider/backend is contacted.
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/mode") return fulfill(route, { mode: "legacy_bearer" });
    if (path === "/api/dashboard") return fulfill(route, dashboard);
    if (handle) return handle(route, path);
    throw new Error(`Unexpected API path: ${path}`);
  });
  await page.goto("/"); await page.getByRole("button", { name: "AI Workspace", exact: true }).click();
}

test("rapid Execute double click and rerender create one logical paid submission", async ({ page }) => {
  const keys = new Set<string>(); let posts = 0;
  await setup(page, async (route, path) => {
    if (route.request().method() === "POST") {
      posts++; keys.add(route.request().headers()["idempotency-key"]);
      await route.fulfill({ contentType: "text/event-stream", headers: { "X-Execution-ID": id }, body: 'data: {"type":"result","report":"Saved report"}\n\n' });
    } else if (path.startsWith("/api/executions/")) await fulfill(route, descriptor("completed"));
    else await fulfill(route, result());
  });
  await page.getByRole("textbox", { name: "Task for agents" }).fill("Offline task");
  await page.locator("form.composer").evaluate(form => { (form as HTMLFormElement).requestSubmit(); (form as HTMLFormElement).requestSubmit(); });
  await expect(page.getByRole("region", { name: "Submission status" }).or(page.locator('[aria-label="Submission status"]'))).toContainText("Completed");
  expect(posts).toBe(1); expect(keys.size).toBe(1);
  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await page.getByRole("button", { name: "Check status", exact: true }).click();
  await expect(page.getByText("Saved report", { exact: true }).first()).toBeVisible();
  expect(posts).toBe(1);
});

test("202 refresh reconnects by GET and interrupted partial output remains visible", async ({ page }) => {
  let posts = 0, state = "running";
  await setup(page, async (route, path) => {
    if (route.request().method() === "POST") { posts++; return fulfill(route, descriptor("running"), 202); }
    if (path.startsWith("/api/executions/")) return fulfill(route, descriptor(state));
    return fulfill(route, result(state));
  });
  await page.getByRole("textbox", { name: "Task for agents" }).fill("Offline task");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(page.locator('[aria-label="Submission status"]')).toContainText("Running");
  state = "interrupted";
  await page.reload(); await page.getByRole("button", { name: "AI Workspace", exact: true }).click();
  await expect(page.locator('[aria-label="Submission status"]')).toContainText("Interrupted / recovery required");
  await expect(page.getByText("Saved report", { exact: true }).first()).toBeVisible();
  expect(posts).toBe(1);
  const metadata = await page.evaluate(() => sessionStorage.getItem("agentflow.executions.v1"));
  expect(metadata).not.toContain("Offline task");
});

test("network failure retry uses the original key and safe conflict never changes it", async ({ page }) => {
  const keys: string[] = [];
  await setup(page, async (route, path) => {
    if (route.request().method() === "POST") {
      keys.push(route.request().headers()["idempotency-key"]);
      if (keys.length === 1) return route.abort("connectionfailed");
      return fulfill(route, { detail: "Idempotency key was already used for a different request" }, 409);
    }
    if (path.startsWith("/api/executions/")) return fulfill(route, { detail: "Execution not found" }, 404);
    throw new Error(`Unexpected path ${path}`);
  });
  await page.getByRole("textbox", { name: "Task for agents" }).fill("Offline task");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(page.locator('[aria-label="Submission status"]')).toContainText("state unknown");
  await page.getByRole("button", { name: "Retry same submission", exact: true }).click();
  await expect(page.locator('[aria-label="Submission status"]').getByRole("alert")).toContainText("Idempotency key was already used");
  expect(keys).toHaveLength(2); expect(keys[1]).toBe(keys[0]);
});

for (const status of [401, 429, 503, 504]) test(`UI handles HTTP ${status} without automatically retrying a paid call`, async ({ page }) => {
  let posts = 0;
  await setup(page, async route => { posts++; await fulfill(route, { detail: `Safe server failure ${status}` }, status); });
  await page.getByRole("textbox", { name: "Task for agents" }).fill("Offline task");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  if (status === 401) await expect(page.getByRole("heading", { name: "Connect to AgentFlow" })).toBeVisible();
  else await expect(page.locator('[aria-label="Submission status"]').getByRole("alert")).toContainText(`Safe server failure ${status}`);
  expect(posts).toBe(1);
});

test("custom workflow uses the existing run status contract on duplicate 202", async ({ page }) => {
  let posts = 0;
  const agent = { id: agentId, name: "Offline agent", provider: "gemini", model: "gemini-3.5-flash-lite", enabled: true };
  const workflow = { id: workflowId, name: "Offline workflow", description: "Offline", enabled: true, agent_ids: [agentId] };
  await setup(page, async (route, path) => {
    if (path === "/api/agents") return fulfill(route, [agent]);
    if (path === "/api/custom-workflows") return fulfill(route, [workflow]);
    const run = { id: taskId, workflow_id: workflowId, status: "completed", task: "Offline", created_at: new Date().toISOString(), result: "Custom saved output", steps: [{ position: 0, agent_name: "Offline agent", status: "completed", output: "Custom saved output" }] };
    if (route.request().method() === "POST") { posts++; expect(route.request().headers()["idempotency-key"]).toBeTruthy(); return fulfill(route, { ...descriptor("completed"), task_id: null, workflow_run_id: taskId }, 202); }
    if (path.startsWith("/api/executions/")) return fulfill(route, { ...descriptor("completed"), task_id: null, workflow_run_id: taskId });
    if (path.endsWith("/runs")) return fulfill(route, [run]);
    if (path === `/api/custom-workflows/runs/${taskId}`) return fulfill(route, run);
    throw new Error(`Unexpected API path ${path}`);
  });
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await page.getByRole("button", { name: "View / Run" }).click();
  await page.getByRole("textbox", { name: "Task", exact: true }).fill("Offline workflow task");
  await page.getByRole("button", { name: "Run workflow", exact: true }).click();
  await expect(page.getByText("Custom saved output", { exact: true }).first()).toBeVisible();
  expect(posts).toBe(1);
});

test("custom agent restores the existing execution from agent history after 202", async ({ page }) => {
  let posts = 0;
  const agent = { id: agentId, name: "Offline specialist", provider: "gemini", model: "gemini-3.5-flash-lite", enabled: true,
    role: "Offline", description: "Offline", system_instructions: "Offline", temperature: 0.7, max_output_tokens: 4096 };
  const execution = { id: taskId, agent_id: agentId, task: "Offline", status: "completed", result: "Agent saved output", created_at: new Date().toISOString() };
  await setup(page, async (route, path) => {
    if (path === "/api/agents") return fulfill(route, [agent]);
    if (path === "/api/agents/options") return fulfill(route, { providers: [{ provider: "gemini", models: [agent.model] }] });
    if (route.request().method() === "POST") { posts++; expect(route.request().headers()["idempotency-key"]).toBeTruthy(); return fulfill(route, { ...descriptor("completed"), task_id: null, agent_execution_id: taskId }, 202); }
    if (path.startsWith("/api/executions/")) return fulfill(route, { ...descriptor("completed"), task_id: null, agent_execution_id: taskId });
    if (path === `/api/agents/${agentId}/executions`) return fulfill(route, [execution]);
    throw new Error(`Unexpected path ${path}`);
  });
  await page.getByRole("button", { name: "Agent Studio", exact: true }).click();
  await page.getByRole("button", { name: "Run Agent", exact: true }).click();
  await page.getByRole("textbox", { name: "Task for this agent" }).fill("Offline agent task");
  await page.getByRole("dialog", { name: "Run Offline specialist" }).getByRole("button", { name: "Run agent", exact: true }).click();
  await expect(page.getByText("Agent saved output", { exact: true })).toBeVisible();
  expect(posts).toBe(1);
});
