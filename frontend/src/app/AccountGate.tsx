"use client";

import { FormEvent, ReactNode, useEffect, useState } from "react";
import { accountTabId, apiFetch, fetchAuthMode, setAccountMode, setAccountSession } from "./api";

type Profile = { id: string; login: string; role: string; csrf_token: string };

export function AccountGate({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<"loading" | "accounts" | "legacy_bearer" | "failed">("loading");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [changePassword, setChangePassword] = useState(false);

  useEffect(() => {
    let active = true;
    const expired = () => { setProfile(null); setChangePassword(false); setError("Your session expired. Please sign in again."); };
    window.addEventListener("agentflow-auth-expired", expired);
    const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("agentflow-account-change") : null;
    if (channel) channel.onmessage = event => {
      if (event.data?.source !== accountTabId) window.location.reload();
    };
    async function initialize() {
      try {
        const response = await fetchAuthMode();
        // Explicit compatibility with V1, whose middleware protects unknown API paths.
        if ([401, 404].includes(response.status)) { if (active) setMode("legacy_bearer"); return; }
        if (!response.ok) throw new Error("Authentication service is unavailable.");
        const body = await response.json();
        if (!["accounts", "legacy_bearer"].includes(body.mode)) throw new Error("Unsupported authentication mode.");
        setAccountMode(body.mode === "accounts");
        if (body.mode === "accounts") {
          const me = await apiFetch("/api/auth/me");
          if (me.ok) {
            const user: Profile = await me.json();
            if (active) { setAccountSession(user.id, user.csrf_token, false); setProfile(user); }
          } else if (me.status !== 401) throw new Error("Could not verify your session.");
        }
        if (active) setMode(body.mode);
      } catch (e) {
        if (active) { setError(e instanceof Error ? e.message : "Could not connect."); setMode("failed"); }
      }
    }
    void initialize();
    return () => { active = false; channel?.close(); window.removeEventListener("agentflow-auth-expired", expired); };
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const fields = new FormData(form);
    try {
      const response = await apiFetch("/api/auth/login", { method: "POST",
        headers: { "X-AgentFlow-Login": "1" },
        body: JSON.stringify({ login: fields.get("login"), password: fields.get("password") }) });
      if (!response.ok) throw new Error(response.status === 429 ? "Too many attempts. Try again in five minutes." : "Sign in failed. Check your credentials and try again.");
      const body = await response.json();
      setAccountSession(body.id, body.csrf_token);
      const responseMe = await apiFetch("/api/auth/me");
      if (!responseMe.ok) throw new Error("Could not verify your session.");
      setProfile(await responseMe.json()); form.reset();
    } catch (e) { setError(e instanceof Error ? e.message : "Sign in failed."); }
    finally { setBusy(false); }
  }

  async function signOut() {
    setBusy(true); setError("");
    try {
      const response = await apiFetch("/api/auth/logout", { method: "POST" });
      if (!response.ok && response.status !== 401) throw new Error("Sign out failed. Please try again.");
      setAccountSession(null, null); setProfile(null); setChangePassword(false);
    } catch (e) { setError(e instanceof Error ? e.message : "Sign out failed."); }
    finally { setBusy(false); }
  }

  async function updatePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const fields = new FormData(event.currentTarget);
    try {
      const response = await apiFetch("/api/auth/password", { method: "POST", body: JSON.stringify({
        current_password: fields.get("current"), new_password: fields.get("new") }) });
      if (!response.ok) throw new Error("Password change failed. Check your current password and try again.");
      setAccountSession(null, null); setProfile(null); setChangePassword(false);
      setError("Password changed. Sign in with your new password.");
    } catch (e) { setError(e instanceof Error ? e.message : "Password change failed."); }
    finally { setBusy(false); }
  }

  if (mode === "legacy_bearer") return children;
  if (mode === "loading") return <main className="shell"><section className="auth-gate card" role="status">Checking your session…</section></main>;
  if (mode === "failed") return <main className="shell"><section className="auth-gate card" role="alert">{error}<button onClick={() => window.location.reload()}>Retry connection</button></section></main>;
  if (!profile) return <main className="shell"><section className="auth-gate card"><h1>Sign in to AgentFlow</h1><p>Use the account provided by your administrator.</p>{error && <p role="alert">{error}</p>}<form onSubmit={signIn}><label htmlFor="login">Account</label><input name="login" id="login" autoComplete="username" required maxLength={254}/><label htmlFor="password">Password</label><input name="password" id="password" type="password" autoComplete="current-password" required maxLength={128}/><button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form></section></main>;
  return <><div className="account-toolbar"><span>{profile.login} · {profile.role}</span><button onClick={() => setChangePassword(!changePassword)}>Change password</button><button onClick={signOut} disabled={busy}>Sign out</button>{error && <span role="alert">{error}</span>}{changePassword && <form onSubmit={updatePassword}><label>Current password <input name="current" type="password" autoComplete="current-password" required maxLength={128}/></label><label>New password (15–128 characters) <input name="new" type="password" autoComplete="new-password" minLength={15} maxLength={128} required/></label><button disabled={busy}>Save password</button></form>}</div><div key={profile.id}>{children}</div></>;
}
