import { test, expect } from "@playwright/test";

test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: "ignoreErrors" }); });

test("account login, reload, password change and logout keep credentials out of browser storage", async ({ page }) => {
  let signedIn = false, passwordChanged = false;
  const profile = { id: "synthetic-account-a", login: "member-a", role: "member", csrf_token: "synthetic-csrf" };
  await page.addInitScript(() => sessionStorage.setItem("agentflow_api_token", "old-shared-token"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const headers = route.request().headers();
    expect(headers.authorization).toBeUndefined();
    if (path === "/api/auth/mode") return route.fulfill({ json: { mode: "accounts" } });
    if (path === "/api/auth/login") {
      expect(headers["x-agentflow-login"]).toBe("1");
      expect(route.request().postDataJSON().login).toBe("member-a");
      signedIn = true; return route.fulfill({ json: profile });
    }
    if (path === "/api/auth/me") return route.fulfill({ status: signedIn ? 200 : 401,
      json: signedIn ? profile : { detail: "Authentication required" } });
    if (["/api/auth/logout", "/api/auth/password"].includes(path)) {
      expect(method).toBe("POST"); expect(headers["x-csrf-token"]).toBe("synthetic-csrf");
      passwordChanged ||= path.endsWith("password");
      signedIn = false; return route.fulfill({ status: 204 });
    }
    if (path === "/api/dashboard") return route.fulfill({ json: { agents: 5, provider: "gemini",
      model: "offline", history: [], completed: 0, failed: 0, workflows: 0 } });
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to AgentFlow" })).toBeVisible();
  async function login() {
    await page.getByLabel("Account", { exact: true }).fill("member-a");
    await page.getByLabel("Password", { exact: true }).fill("synthetic-password-only");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  }
  await login();
  const storage = await page.evaluate(() => JSON.stringify({ ...sessionStorage, ...localStorage }));
  expect(storage).not.toContain("synthetic-password");
  expect(storage).not.toContain("synthetic-csrf");
  expect(storage).not.toContain("old-shared-token");
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByRole("button", { name: "Change password" }).click();
  await page.getByLabel("Current password").fill("synthetic-password-only");
  await page.getByLabel("New password (15–128 characters)").fill("new-synthetic-password");
  await page.getByRole("button", { name: "Save password" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to AgentFlow" })).toBeVisible();
  expect(passwordChanged).toBe(true);
  await login();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to AgentFlow" })).toBeVisible();
});

test("account service errors fail closed without offering a shared token", async ({ page }) => {
  await page.route("**/api/auth/mode", route => route.fulfill({ status: 503, json: {} }));
  await page.goto("/");
  await expect(page.locator("section[role=alert]")).toContainText("unavailable");
  await expect(page.getByLabel("API access token")).toHaveCount(0);
});

test("expired sessions remove private workspace contents", async ({ page }) => {
  let expired = false;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/mode") return route.fulfill({ json: { mode: "accounts" } });
    if (path === "/api/auth/me") return route.fulfill({ json: {
      id: "synthetic-account", login: "member-a", role: "member", csrf_token: "synthetic-csrf" } });
    if (path === "/api/dashboard") return route.fulfill({ json: { history: [], agents: 5 } });
    if (path === "/api/agents") { expired = true; return route.fulfill({ status: 401, json: {} }); }
    if (path === "/api/agents/options") return route.fulfill({ json: { providers: [] } });
    return route.fulfill({ status: 401, json: {} });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Studio", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in to AgentFlow" })).toBeVisible();
  expect(expired).toBe(true);
  await expect(page.getByRole("button", { name: "AI Workspace", exact: true })).toHaveCount(0);
});

test("failed and throttled login keep the workspace locked", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/mode") return route.fulfill({ json: { mode: "accounts" } });
    if (path === "/api/auth/login") return route.fulfill({ status: ++attempts === 1 ? 401 : 429, json: {} });
    return route.fulfill({ status: 401, json: {} });
  });
  await page.goto("/");
  await page.getByLabel("Account", { exact: true }).fill("member-a");
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("section [role=alert]")).toContainText("Sign in failed");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("section [role=alert]")).toContainText("Too many attempts");
  await expect(page.getByRole("button", { name: "AI Workspace", exact: true })).toHaveCount(0);
  expect(attempts).toBe(2);
});

test("sign-out reaches other tabs without a logged-out reload loop", async ({ context }) => {
  let signedIn = true;
  const profile = { id: "synthetic-account", login: "member-a", role: "member", csrf_token: "synthetic-csrf" };
  await context.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/mode") return route.fulfill({ json: { mode: "accounts" } });
    if (path === "/api/auth/me") return route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? profile : {} });
    if (path === "/api/auth/logout") { signedIn = false; return route.fulfill({ status: 204 }); }
    return route.fulfill({ json: { history: [], agents: 5 } });
  });
  const first = await context.newPage(), second = await context.newPage();
  await context.addInitScript(() => {
    sessionStorage.setItem("fixture_document_loads", String(Number(sessionStorage.getItem("fixture_document_loads") || 0) + 1));
  });
  await first.goto("/");
  await second.goto("/");
  await expect(first.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(second.getByRole("button", { name: "Sign out" })).toBeVisible();
  const firstLoads = await first.evaluate(() => sessionStorage.getItem("fixture_document_loads"));
  const secondLoads = await second.evaluate(() => sessionStorage.getItem("fixture_document_loads"));
  await first.getByRole("button", { name: "Sign out" }).click();
  for (const tab of [first, second]) {
    await expect(tab.getByRole("heading", { name: "Sign in to AgentFlow" })).toBeVisible();
    await expect(tab.getByRole("button", { name: "AI Workspace", exact: true })).toHaveCount(0);
  }
  expect(await first.evaluate(() => sessionStorage.getItem("fixture_document_loads"))).toBe(firstLoads);
  expect(Number(await second.evaluate(() => sessionStorage.getItem("fixture_document_loads")))).toBe(Number(secondLoads) + 1);
  await context.unrouteAll({ behavior: "ignoreErrors" });
});

test("a different account clears the previous owner's execution identities", async ({ page }) => {
  let login = "member-a", signedIn = true;
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    const profile = { id: login, login, role: "member", csrf_token: "synthetic-csrf" };
    if (path === "/api/auth/mode") return route.fulfill({ json: { mode: "accounts" } });
    if (path === "/api/auth/me") return route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? profile : {} });
    if (path === "/api/auth/logout") { signedIn = false; return route.fulfill({ status: 204 }); }
    if (path === "/api/auth/login") {
      login = route.request().postDataJSON().login; signedIn = true;
      return route.fulfill({ json: { ...profile, id: login } });
    }
    return route.fulfill({ json: { history: [], agents: 5 } });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.evaluate(() => sessionStorage.setItem("agentflow.executions.v1", "previous-owner-marker"));
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Account", { exact: true }).fill("member-b");
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("agentflow_account_id"))).toBe("member-b");
  expect(await page.evaluate(() => sessionStorage.getItem("agentflow.executions.v1"))).toBeNull();
});
