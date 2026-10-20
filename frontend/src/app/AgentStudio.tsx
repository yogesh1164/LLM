"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AppIcon } from "./AppIcon";
import { apiFetch } from "./api";
import "./agent-studio.css";
import { CustomAgentRunner } from "./CustomAgentRunner";

type Provider = "gemini" | "openai";
type Agent = {
  id: string;
  name: string;
  description: string;
  role: string;
  system_instructions: string;
  provider: Provider;
  model: string;
  temperature: number;
  max_output_tokens: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};
type AgentForm = Omit<Agent, "id" | "created_at" | "updated_at">;
type ProviderOption = { provider: Provider; models: string[] };
type AgentOptions = { providers: ProviderOption[] };

const builtins = [
  { name: "Orchestrator", role: "Workflow coordination", description: "Routes tasks through the fixed five-stage workflow." },
  { name: "Research", role: "Evidence gathering", description: "Finds current evidence and source links." },
  { name: "Analysis", role: "Reasoning", description: "Identifies implications, patterns, and uncertainties." },
  { name: "Report", role: "Report writing", description: "Creates a clear, structured report from workflow context." },
  { name: "Review", role: "Quality review", description: "Checks quality and flags unsupported claims." },
];

const emptyForm = (options: AgentOptions | null): AgentForm => {
  const provider = options?.providers[0];
  return {
    name: "",
    description: "",
    role: "",
    system_instructions: "",
    provider: provider?.provider ?? "gemini",
    model: provider?.models[0] ?? "",
    temperature: 0.7,
    max_output_tokens: 4096,
    enabled: true,
  };
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: string };
      if (body.detail) message = body.detail;
    } catch { /* Non-JSON server errors use the safe status message. */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function AgentStudio() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [options, setOptions] = useState<AgentOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [formTarget, setFormTarget] = useState<Agent | "new" | null>(null);
  const [form, setForm] = useState<AgentForm>(() => emptyForm(null));
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [runAgent, setRunAgent] = useState<Agent | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [items, providerOptions] = await Promise.all([
        apiRequest<Agent[]>("/api/agents"),
        apiRequest<AgentOptions>("/api/agents/options"),
      ]);
      setAgents(items);
      setOptions(providerOptions);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load custom agents.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (formTarget && !dialog.open) dialog.showModal();
    else if (!formTarget && dialog.open) dialog.close();
  }, [formTarget]);

  function startCreate() {
    setForm(emptyForm(options));
    setFormTarget("new");
    setFormError("");
  }

  function startEdit(agent: Agent) {
    setForm({
      name: agent.name,
      description: agent.description,
      role: agent.role,
      system_instructions: agent.system_instructions,
      provider: agent.provider,
      model: agent.model,
      temperature: agent.temperature,
      max_output_tokens: agent.max_output_tokens,
      enabled: agent.enabled,
    });
    setFormTarget(agent);
    setFormError("");
  }

  async function saveAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setSaving(true);
    const editing = formTarget !== "new" && formTarget !== null;
    try {
      const saved = await apiRequest<Agent>(editing ? `/api/agents/${formTarget.id}` : "/api/agents", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(form),
      });
      setFormTarget(null);
      setNotice(editing ? `Saved ${saved.name}.` : `Created ${saved.name}.`);
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not save this agent.");
    } finally {
      setSaving(false);
    }
  }

  async function duplicateAgent(agent: Agent) {
    setBusyId(agent.id);
    setNotice("");
    try {
      const duplicate = await apiRequest<Agent>(`/api/agents/${agent.id}/duplicate`, { method: "POST" });
      setNotice(`Created ${duplicate.name}.`);
      await load();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not duplicate this agent.");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleAgent(agent: Agent) {
    setBusyId(agent.id);
    setLoadError("");
    try {
      await apiRequest<Agent>(`/api/agents/${agent.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !agent.enabled }),
      });
      await load();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not update this agent.");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteAgent(agent: Agent) {
    if (!window.confirm(`Delete “${agent.name}”? This cannot be undone.`)) return;
    setBusyId(agent.id);
    setLoadError("");
    try {
      await apiRequest<void>(`/api/agents/${agent.id}`, { method: "DELETE" });
      setNotice(`Deleted ${agent.name}.`);
      await load();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not delete this agent.");
    } finally {
      setBusyId(null);
    }
  }

  function changeProvider(provider: Provider) {
    const model = options?.providers.find((item) => item.provider === provider)?.models[0] ?? "";
    setForm((current) => ({ ...current, provider, model }));
  }

  const selectedProvider = options?.providers.find((item) => item.provider === form.provider);
  const editing = formTarget !== "new" && formTarget !== null;

  return (
    <section className="agent-studio" aria-labelledby="agent-studio-title">
      <div className="studio-intro">
        <div><div className="eyebrow">YOUR SPECIALIST TEAM</div><h1 id="agent-studio-title">Agent Studio</h1>
          <p>Create, manage, and run custom agents individually. Custom agents are not part of the built-in workflow yet.</p></div>
        <button className="primary" type="button" onClick={startCreate} disabled={!options}>
          <AppIcon name="plus" /> Create agent
        </button>
      </div>

      {notice && <div className="studio-notice" role="status">{notice}<button type="button" onClick={() => setNotice("")} aria-label="Dismiss notification">Dismiss</button></div>}
      {loadError && <div className="notice error" role="alert">{loadError}<button className="secondary" type="button" onClick={() => void load()}>Retry</button></div>}

      <section className="studio-section" aria-labelledby="builtin-agents-title">
        <div className="studio-section-heading"><div><h2 id="builtin-agents-title">Built-in workflow agents</h2>
          <p>Fixed stages used by the existing workflow. These are protected and are not stored as custom configurations.</p></div>
          <span className="studio-count">5 built-in</span></div>
        <div className="studio-grid">
          {builtins.map((agent) => <article className="card studio-agent builtin-agent" key={agent.name}>
            <div className="studio-agent-head"><span className="agent-symbol large"><AppIcon name="agents" /></span><span className="builtin-badge">Built in · Protected</span></div>
            <h3>{agent.name}</h3><p>{agent.description}</p>
            <div className="studio-agent-meta"><span>Role</span><b>{agent.role}</b></div>
            <div className="studio-card-footer">Part of the fixed five-stage workflow</div>
          </article>)}
        </div>
      </section>

      <section className="studio-section" aria-labelledby="custom-agents-title">
        <div className="studio-section-heading"><div><h2 id="custom-agents-title">Custom agents</h2>
          <p>Saved in the database. Enabled Gemini agents can be run independently.</p></div>
          {!loading && <span className="studio-count">{agents.length} {agents.length === 1 ? "agent" : "agents"}</span>}</div>
        {loading ? <div className="studio-state" role="status"><span className="spinner" /> Loading custom agents…</div>
          : agents.length ? <div className="studio-grid">
            {agents.map((agent) => <article className="card studio-agent" key={agent.id}>
              <div className="studio-agent-head"><span className="agent-symbol large"><AppIcon name="agents" /></span>
                <span className={`custom-agent-status ${agent.enabled ? "enabled" : "disabled"}`}>{agent.enabled ? "Enabled" : "Disabled"}</span></div>
              <h3>{agent.name}</h3><p className="custom-agent-description">{agent.description || "No description provided."}</p>
              <div className="studio-agent-meta"><span>Role</span><b>{agent.role}</b></div>
              <div className="studio-agent-meta"><span>Provider</span><b>{agent.provider} · {agent.model}</b></div>
              <div className="studio-agent-meta"><span>Settings</span><b>Temperature {agent.temperature} · {agent.max_output_tokens.toLocaleString()} tokens</b></div>
              <div className="studio-card-footer">
                <button type="button" className="studio-action" disabled={!agent.enabled || agent.provider !== "gemini" || busyId === agent.id} onClick={() => setRunAgent(agent)}>Run Agent</button>
                <button type="button" className="studio-action" onClick={() => startEdit(agent)}>Edit</button>
                <button type="button" className="studio-action" disabled={busyId === agent.id} onClick={() => void duplicateAgent(agent)}>{busyId === agent.id ? "Working…" : "Duplicate"}</button>
                <button type="button" className="studio-action" disabled={busyId === agent.id} onClick={() => void toggleAgent(agent)}>{agent.enabled ? "Disable" : "Enable"}</button>
                <button type="button" className="studio-action destructive" disabled={busyId === agent.id} onClick={() => void deleteAgent(agent)}>Delete</button>
              </div>
            </article>)}
          </div> : <div className="studio-state studio-empty"><span className="agent-symbol large"><AppIcon name="agents" /></span>
            <b>{options ? "No custom agents yet" : "Agent Studio is unavailable"}</b>
            <p>{options ? "Create your first saved agent configuration to get started." : "Connect to the AgentFlow API to load provider and model options."}</p>
          </div>}
      </section>

      <dialog className="agent-form-dialog" ref={dialogRef} aria-labelledby="agent-form-title"
        onCancel={(event) => { event.preventDefault(); setFormTarget(null); }} onClose={() => setFormTarget(null)}>
        <form className="agent-form" onSubmit={saveAgent}>
          <header><div><div className="eyebrow">CUSTOM CONFIGURATION</div><h2 id="agent-form-title">{editing ? "Edit agent" : "Create agent"}</h2></div>
            <button type="button" className="studio-dialog-close" onClick={() => setFormTarget(null)} aria-label="Close form"><AppIcon name="close" /></button></header>
          {formError && <div className="notice error" role="alert">{formError}</div>}
          <div className="agent-form-grid">
            <label>Agent name<input required minLength={1} maxLength={80} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label>Role<input required maxLength={100} value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })} /></label>
            <label className="wide-field">Description<textarea maxLength={500} rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <label className="wide-field">System instructions<textarea required minLength={1} maxLength={8000} rows={7} value={form.system_instructions} onChange={(event) => setForm({ ...form, system_instructions: event.target.value })} /></label>
            <label>Provider<select value={form.provider} onChange={(event) => changeProvider(event.target.value as Provider)}>
              {options?.providers.map((item) => <option key={item.provider} value={item.provider}>{item.provider}</option>)}
            </select></label>
            <label>Model<select value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })}>
              {selectedProvider?.models.map((model) => <option key={model} value={model}>{model}</option>)}
            </select></label>
            <label>Temperature<input type="number" min="0" max="2" step="0.1" required value={form.temperature} onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })} /></label>
            <label>Maximum output tokens<input type="number" min="1" max="32768" step="1" required value={form.max_output_tokens} onChange={(event) => setForm({ ...form, max_output_tokens: Number(event.target.value) })} /></label>
            <label className="agent-enabled-field"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /> Enabled</label>
          </div>
          <p className="form-note">Agent settings are saved here. Run enabled Gemini agents independently; the five-agent workflow stays unchanged.</p>
          <footer><button className="secondary" type="button" onClick={() => setFormTarget(null)}>Cancel</button>
            <button className="primary" type="submit" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Create agent"}</button></footer>
        </form>
      </dialog>
      {runAgent && <CustomAgentRunner agent={runAgent} onClose={() => setRunAgent(null)} />}
    </section>
  );
}
