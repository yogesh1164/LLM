const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = typeof window === "undefined"
    ? null
    : window.sessionStorage.getItem("agentflow_api_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  if (response.status === 401 && typeof window !== "undefined") {
    window.sessionStorage.removeItem("agentflow_api_token");
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
  return window.sessionStorage.getItem("agentflow_api_token");
}
