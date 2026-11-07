import { test, expect } from "@playwright/test";

const base = process.env.DURABLE_RUNTIME_BASE_URL;
const token = process.env.DURABLE_RUNTIME_TOKEN;
const accounts = process.env.DURABLE_RUNTIME_ACCOUNTS === "1";
test.describe("offline enabled runtime", () => {
  test.skip(!base || (!token && !accounts), "Run through the guarded offline runtime fixture");
  test.beforeEach(async ({ request, page }) => {
    if (!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error("Runtime tests require a loopback-only fixture URL");
    const health = await request.get(base + "/api/health");
    expect(health.headers()["x-agentflow-offline-fixture"]).toBe("1");
    if (accounts) {
      const login = await request.post(base + "/api/auth/login", { headers: {
        Origin: "http://127.0.0.1:3307", "X-AgentFlow-Login": "1" },
        data: { login: "browser-admin", password: "offline-browser-password" } });
      expect(login.status()).toBe(200);
      await page.context().addCookies((await request.storageState()).cookies);
    } else await page.addInitScript(value => sessionStorage.setItem("agentflow_api_token", value!), token);
    // Browser sees same-origin /api; only this dedicated, identified fixture receives requests.
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      const response = await route.fetch({ url: base + path });
      await route.fulfill({ response });
    });
  });
  test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "wait" }); });

  for (const surface of ["fixed", "custom_agent", "custom_workflow"]) test(`${surface}: UI, PostgreSQL journal, refresh and GET-only monitoring`, async ({ page, request, playwright }) => {
    const headers: Record<string, string> = accounts ? { Origin: "http://127.0.0.1:3307",
      "X-CSRF-Token": (await (await request.get(base + "/api/auth/me")).json()).csrf_token }
      : { Authorization: "Bearer " + token };
    let agentId = "", workflowId = "";
    const name = "Offline browser " + crypto.randomUUID().slice(0, 8);
    if (surface !== "fixed") {
      const response = await request.post(base + "/api/agents", { headers, data: { name, role: "Offline", description: "Offline fixture",
        system_instructions: "Return offline fixture output", provider: "gemini", model: "gemini-3.5-flash-lite", enabled: true, temperature: 0.7, max_output_tokens: 4096 } });
      expect(response.status()).toBe(201); agentId = (await response.json()).id;
    }
    if (surface === "custom_workflow") {
      const response = await request.post(base + "/api/custom-workflows", { headers, data: { name, description: "Offline fixture", enabled: true, agent_ids: [agentId] } });
      expect(response.status()).toBe(201); workflowId = (await response.json()).id;
    }
    const path = surface === "fixed" ? "/api/workflows/stream" : surface === "custom_agent" ? `/api/agents/${agentId}/execute` : `/api/custom-workflows/${workflowId}/execute`;
    let posts = 0;
    page.on("request", request => { if (new URL(request.url()).pathname === path && request.method() === "POST") posts++; });
    const open = async () => {
      await page.goto("/");
      if (surface === "fixed") await page.getByRole("button", { name: "AI Workspace", exact: true }).click();
      else if (surface === "custom_agent") {
        await page.getByRole("button", { name: "Agent Studio", exact: true }).click();
        await page.locator("article").filter({ hasText: name }).getByRole("button", { name: "Run Agent", exact: true }).click();
      } else {
        await page.getByRole("button", { name: "Workflows", exact: true }).click();
        await page.locator("article").filter({ hasText: name }).getByRole("button", { name: "View / Run", exact: true }).click();
      }
    };
    await open();
    const task = page.getByRole("textbox", { name: surface === "fixed" ? "Task for agents" : surface === "custom_agent" ? "Task for this agent" : "Task", exact: true });
    await task.fill("OFFLINE-RUNTIME browser-" + surface);
    const form = page.locator(surface === "fixed" ? "form.composer" : surface === "custom_agent" ? "form.custom-runner-form" : "form.wb-run-form");
    await form.evaluate(form => { (form as HTMLFormElement).requestSubmit(); (form as HTMLFormElement).requestSubmit(); });
    await expect(page.locator('[aria-label="Submission status"]')).toContainText("Completed");
    const text = surface === "fixed" ? "Offline stage 4 output" : "Offline stage 1 output";
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible();
    const id = await page.evaluate(path => JSON.parse(sessionStorage.getItem("agentflow.executions.v1")!)[path].executionId, path);
    const journal = await request.get(base + "/api/executions/" + id, { headers });
    expect((await journal.json()).state).toBe("completed");
    if (accounts) {
      const other = await playwright.request.newContext();
      try {
        const login = await other.post(base + "/api/auth/login", { headers: {
          Origin: "http://127.0.0.1:3307", "X-AgentFlow-Login": "1" },
          data: { login: "browser-member", password: "offline-browser-password" } });
        expect(login.status()).toBe(200);
        expect((await other.get(base + "/api/executions/" + id)).status()).toBe(404);
        if (agentId) expect((await other.get(base + "/api/agents/" + agentId)).status()).toBe(404);
        if (workflowId) expect((await other.get(base + "/api/custom-workflows/" + workflowId)).status()).toBe(404);
      } finally { await other.dispose(); }
    }
    await open();
    await expect(page.locator('[aria-label="Submission status"]')).toContainText("Completed");
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Check status", exact: true }).click();
    await expect(page.getByRole("button", { name: "Check status", exact: true })).toBeEnabled();
    expect(posts).toBe(1);
  });
});
