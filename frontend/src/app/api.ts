// Local development uses the same-origin /api proxy. Production retains the
// configured API URL (or the existing localhost fallback).
const apiBase = process.env.NODE_ENV === "development"
  ? ""
  : process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
let accountMode = false;
let accountId: string | null = null;
let csrfToken: string | null = null;
let authGeneration = 0;
// Each document ignores its own broadcasts; other tabs reload cookie identity.
export const accountTabId = crypto.randomUUID();

export function fetchAuthMode(): Promise<Response> {
  return fetch(`${apiBase}/api/auth/mode`, { credentials: "omit" });
}

export function setAccountMode(enabled: boolean) {
  accountMode = enabled;
  if (enabled) window.sessionStorage.removeItem("agentflow_api_token");
}

export function setAccountSession(id: string | null, csrf: string | null, notifyOtherTabs = true) {
  if (id !== accountId) authGeneration++;
  if (id && window.sessionStorage.getItem("agentflow_account_id") !== id) {
    window.sessionStorage.removeItem("agentflow.executions.v1");
  }
  accountId = id; csrfToken = csrf;
  if (id) window.sessionStorage.setItem("agentflow_account_id", id);
  // Keep non-secret owner-tagged submission metadata across expiry/sign-out.
  // A different account clears it before mounting its workspace.
  window.dispatchEvent(new Event("agentflow-auth-changed"));
  if (notifyOtherTabs && typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel("agentflow-account-change");
    channel.postMessage({ source: accountTabId }); channel.close();
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const generation = authGeneration;
  const token = accountMode || typeof window === "undefined"
    ? null
    : window.sessionStorage.getItem("agentflow_api_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (accountMode && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${apiBase}${path}`, { ...init, headers,
    credentials: accountMode ? "include" : "same-origin" });
  if (generation !== authGeneration) throw new Error("Account changed; request discarded");
  if (response.status === 401 && typeof window !== "undefined") {
    window.sessionStorage.removeItem("agentflow_api_token");
    if (accountMode) setAccountSession(null, null, accountId !== null);
    window.dispatchEvent(new Event("agentflow-auth-expired"));
    window.dispatchEvent(new Event("agentflow-auth-changed"));
  }
  return response;
}

export function subscribeApiToken(callback: () => void): () => void {
  window.addEventListener("agentflow-auth-changed", callback);
  window.addEventListener("agentflow-auth-expired", callback);
  return () => {
    window.removeEventListener("agentflow-auth-changed", callback);
    window.removeEventListener("agentflow-auth-expired", callback);
  };
}

export function getApiTokenSnapshot(): string | null {
  if (accountMode) return accountId;
  return window.sessionStorage.getItem("agentflow_api_token");
}
