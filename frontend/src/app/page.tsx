"use client";

import { FormEvent, useEffect, useState, useSyncExternalStore } from "react";
import { ResultsPanel, type AgentStage } from "./ResultsPanel";
import { AgentStudio } from "./AgentStudio";
import { WorkflowBuilder } from "./WorkflowBuilder";
import { AppIcon, type IconName } from "./AppIcon";
import { apiFetch, getApiTokenSnapshot, subscribeApiToken } from "./api";
import { useDurableExecution } from "./useDurableExecution";
import { ExecutionNotice } from "./ExecutionNotice";
import { AccountGate } from "./AccountGate";
import "./results.css";
import "./tasks.css";

type Stage = AgentStage & { retry?: string };
type Run = { id: string; status: string; task: string; created_at: string; error?: string | null; elapsed_ms?: number | null; total_tokens?: number | null; estimated_cost?: number | null; stages?: Stage[] };
type Dashboard = { agents: number; provider: string; model: string; web_search_enabled: boolean; completed: number; failed: number; workflows: number; token_usage: number | null; estimated_cost: number | null; history: Run[] };
type Source = { url: string; title?: string | null };
type Result = { status?: string; task_id?: string; orchestrator?: string; plan?: string; research?: string; analysis?: string; report?: string; review?: string; sources?: Source[]; total_tokens?: number; input_tokens?: number; output_tokens?: number; estimated_cost?: number; stages?: Stage[] };
type SavedTask = { id: string; task: string; status: string; result?: Result | null; stages?: Stage[]; error?: string | null; elapsed_ms?: number | null; created_at: string };
const nav = ["Overview", "AI Workspace", "Agent Studio", "Workflows", "Tasks & Execution", "Knowledge Base", "Reports"];
const navigationIcons: IconName[] = ["overview", "workspace", "agents", "workflow", "tasks", "knowledge", "reports"];
const roster = [
  { name: "Orchestrator", desc: "Coordinates the workflow and agent handoffs", color: "violet", live: true, tools: "Workflow routing" },
  { name: "Research", desc: "Finds current evidence and source links", color: "teal", live: true, tools: "Gemini Google Search grounding" },
  { name: "Analysis", desc: "Finds implications and uncertainties", color: "amber", live: true, tools: "Model knowledge only" },
  { name: "Report", desc: "Creates a clear, structured report", color: "blue", live: true, tools: "Model knowledge only" },
  { name: "Review", desc: "Checks quality and unsupported claims", color: "rose", live: true, tools: "Model knowledge only" },
];
const noSubscribe = () => () => undefined;
const clientReady = () => true;
const serverNotReady = () => false;
export default function Home() {
  return <AccountGate><Workspace/></AccountGate>;
}
function Workspace() {
  const [section, setSection] = useState("Overview");
  const [collapsed, setCollapsed] = useState(false);
  const [light, setLight] = useState(false);
  const [task, setTask] = useState("");
  const execution = useDurableExecution<Result>("/api/workflows/stream");
  const result = execution.data;
  const busy = execution.busy;
  const [data, setData] = useState<Dashboard | null>(null);
  const [apiError, setApiError] = useState("");
  const [liveStages, setStages] = useState<Stage[]>([]);
  const stages = result?.stages ?? liveStages;
  const [reports, setReports] = useState<SavedTask[]>([]);
  const apiToken = useSyncExternalStore(subscribeApiToken, getApiTokenSnapshot, () => null);
  const [tokenInput, setTokenInput] = useState("");
  const authReady = useSyncExternalStore(noSubscribe, clientReady, serverNotReady);
  useEffect(() => {
    const expired = () => setApiError("The API access token was rejected. Enter a valid token to reconnect.");
    window.addEventListener("agentflow-auth-expired", expired);
    return () => window.removeEventListener("agentflow-auth-expired", expired);
  }, []);
  useEffect(() => {
    if (!authReady || !apiToken) return;
    let mounted = true;
    apiFetch("/api/dashboard").then(async (r) => { if (!r.ok) { const body = await r.json(); throw new Error(body.detail ?? "Dashboard API is unavailable"); } return r.json(); })
      .then((d: Dashboard) => { if (mounted) setData(d); }).catch((e: Error) => { if (mounted) setApiError(e.message); });
    return () => { mounted = false; };
  }, [authReady, apiToken]);
  useEffect(() => {
    if (!apiToken) return;
    const controller = new AbortController();
    apiFetch("/api/dashboard", { signal: controller.signal }).then(r => r.ok ? r.json() : null).then((d: Dashboard | null) => { if (d) setData(d); }).catch(() => undefined);
    return () => controller.abort();
  }, [busy, apiToken]);
  useEffect(() => {
    if (!apiToken || section !== "Reports" || !data?.history.length) return;
    let mounted = true;
    Promise.all(data.history.map(run => apiFetch(`/api/tasks/${run.id}`).then(r => r.ok ? r.json() : null).catch(() => null)))
      .then((items: (SavedTask | null)[]) => { if (mounted) setReports(items.filter((item): item is SavedTask => item !== null)); });
    return () => { mounted = false; };
  }, [apiToken, section, data]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (execution.client.getSnapshot().busy) return;
    setStages(["Orchestrator", "Research", "Analysis", "Report", "Review"].map(agent => ({ agent, status: "pending" })));
    const saved = await execution.client.submit(task.trim(), event => {
      if (event.type === "stage_retry" && typeof event.agent === "string") setStages(current => current.map(stage => stage.agent === event.agent ? { ...stage, status: "retrying", retry: `Retry ${event.attempt}/${event.max_attempts} after HTTP ${event.status_code}` } : stage));
      if (event.type === "stage" && typeof event.agent === "string") setStages(current => current.map(stage => stage.agent === event.agent ? { ...stage, status: typeof event.status === "string" ? event.status : "pending", output: typeof event.output === "string" ? event.output : stage.output, error: typeof event.error === "string" ? event.error : stage.error, elapsed_ms: typeof event.elapsed_ms === "number" ? event.elapsed_ms : stage.elapsed_ms } : stage));
    });
    if (saved?.status === "completed") setTask("");
  }
  async function removeTask(taskId: string) {
    if (!window.confirm("Delete this task and its saved stage outputs? This cannot be undone.")) return;
    try {
      const response = await apiFetch(`/api/tasks/${taskId}`, { method: "DELETE" });
      if (!response.ok) { const body = await response.json(); throw new Error(body.detail ?? "Could not delete task"); }
      const refreshed = await apiFetch("/api/dashboard");
      if (refreshed.ok) setData(await refreshed.json());
    } catch (e) {
      setApiError(e instanceof Error ? e.message : "Could not delete task");
    }
  }
  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = tokenInput.trim();
    if (!token) return;
    window.sessionStorage.setItem("agentflow_api_token", token);
    window.dispatchEvent(new Event("agentflow-auth-changed"));
    setApiError("");
    setTokenInput("");
  }
  if (!authReady) return <main className="shell"><section className="auth-gate card" role="status">Connecting to AgentFlow…</section></main>;
  if (!apiToken) return <main className="shell"><section className="auth-gate card"><div className="brand-mark"><AppIcon name="sparkles"/></div><h1>Connect to AgentFlow</h1><p>Enter the API access token configured on the server. It stays in this browser session.</p>{apiError && <div className="notice error" role="alert">{apiError}</div>}<form onSubmit={connect}><label htmlFor="api-token">API access token</label><input id="api-token" type="password" autoComplete="current-password" value={tokenInput} onChange={event => setTokenInput(event.target.value)} required/><button className="primary" type="submit">Connect</button></form></section></main>;
  const active = nav.includes(section) ? section : "Overview";
  return <main className={`shell ${light ? "light" : ""}`}>
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <a className="brand" href="#overview" onClick={() => setSection("Overview")}><span className="brand-mark"><AppIcon name="sparkles"/></span>{!collapsed && <span><b>AgentFlow</b><small>AI WORKSPACE</small></span>}</a>
      <div className="nav-label">WORKSPACE</div><nav>{nav.map((name, i) => <button key={name} onClick={() => { setSection(name); if (window.matchMedia("(max-width: 560px)").matches) setCollapsed(true); }} className={`nav-item ${active === name ? "selected" : ""}`} title={collapsed ? name : undefined}><span className="nav-icon"><AppIcon name={navigationIcons[i]}/></span>{!collapsed && <span>{name}</span>}{!collapsed && name === "Tasks & Execution" && <span className="nav-count">{data?.history.length ?? 0}</span>}</button>)}</nav>
      <div className="sidebar-bottom"><span className="online-dot"/><span>{!collapsed && (apiError ? "API disconnected" : "API connection")}</span>{!collapsed && <span className="connection-state">{apiError ? "Offline" : "Ready"}</span>}</div>
    </aside>
    <section className="main-area" onClick={() => { if (!collapsed && window.matchMedia("(max-width: 560px)").matches) setCollapsed(true); }}><header className="topbar"><div className="crumb"><button className="icon-button menu-toggle" onClick={() => setCollapsed(!collapsed)} aria-label="Toggle sidebar" aria-expanded={!collapsed}><AppIcon name="menu"/></button><span>Workspace</span><b>/</b><strong>{section}</strong></div><div className="top-actions"><span className="environment"><i/> {data ? `${data.provider} · ${data.model}` : "AI provider loading"}</span><button className="icon-button" onClick={() => setLight(!light)} aria-label="Toggle color theme"><AppIcon name={light ? "moon" : "sun"}/></button><div className="avatar">AF</div></div></header>
      <div className="content">
        {section === "Overview" && <><div className="page-heading"><div><div className="eyebrow">{authReady ? new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date()).toUpperCase() : ""}</div><h1>Your workspace, at a glance.</h1><p>Monitor your agents and keep work moving.</p></div><button className="primary" onClick={() => setSection("AI Workspace")}><AppIcon name="plus"/><span>New task</span></button></div>
          {apiError && <div className="notice error" role="alert">{apiError}. Start the FastAPI service to load live workspace data.</div>}
          <div className="metric-grid">{[["Built-in agents", data ? String(data.agents) : "—", "Five fixed workflow stages", "agents"], ["Active workflows", data ? String(data.workflows) : "—", "Currently running", "workflow"], ["Completed tasks", data ? String(data.completed) : "—", "Persisted tasks", "check"], ["Failed tasks", data ? String(data.failed) : "—", "Persisted tasks", "warning"]].map(([label, value, hint, icon]) => <article className="metric card" key={label}><div className="metric-top"><span>{label}</span><span className="metric-icon"><AppIcon name={icon as IconName}/></span></div><strong>{data ? value : <i className="skeleton"/>}</strong><small>{hint}</small></article>)}</div>
          <div className="overview-grid"><section className="card activity-card"><div className="section-head"><div><h2>Recent execution history</h2><p>Persisted workflow runs</p></div><button className="text-button" onClick={() => setSection("Tasks & Execution")}>View all <AppIcon name="arrow"/></button></div>{data?.history.length ? <div className="run-list">{data.history.slice(0, 5).map(run => <RunRow key={run.id} run={run}/>)}</div> : <div className="empty"><span><AppIcon name="clock"/></span><b>{data ? "No executions yet" : "Loading executions"}</b><small>{data ? "Start a task to see real workflow activity here." : "Fetching live dashboard data…"}</small></div>}<div className="usage-strip"><div><small>Token usage · latest 50 tasks</small><b>{data?.token_usage?.toLocaleString() ?? "Unavailable"}</b></div><div><small>Estimated API cost · configured rates</small><b>{data?.estimated_cost != null ? `$${data.estimated_cost.toFixed(6)}` : "Unavailable"}</b></div></div></section>
            <section className="card agent-card"><div className="section-head"><div><h2>Agent activity</h2><p>Your built-in workflow team</p></div><button className="text-button" onClick={() => setSection("Agent Studio")}>Agent studio <AppIcon name="arrow"/></button></div><div className="agent-mini-list">{roster.map((agent, i) => <div className="agent-mini" key={agent.name}><span className={`agent-symbol ${agent.color}`}>{agent.name[0]}</span><div><b>{agent.name}</b><small>{i === 1 ? (data?.web_search_enabled ? (data.provider === "gemini" ? "Google Search grounding enabled" : "Hosted web search enabled") : "Web search disabled") : i === 0 ? "Workflow coordination" : "Model knowledge only"}</small></div><span className="status-pill">Built in</span></div>)}</div><div className="capability-note">Research uses hosted web search when enabled; source links appear with completed runs.</div></section></div>
        </>}
        {section === "AI Workspace" && <><div className="page-heading"><div><div className="eyebrow">MULTI-AGENT WORKSPACE</div><h1>What can your team work on?</h1><p>Submit a task to run Orchestrator → Research → Analysis → Report → Review.</p></div><span className="live-label"><i/> API connected when available</span></div><div className="workspace-layout"><section className="card chat-card"><div className="chat-toolbar"><div><b>New conversation</b><small>Five agent workflow · {data?.provider ?? "AI"} provider</small></div><label>Workflow <select aria-label="Select workflow"><option>Research & report</option></select></label></div><div className="chat-body">{!result && !busy && <div className="welcome"><span className="welcome-mark"><AppIcon name="sparkles"/></span><h2>Make progress on complex work.</h2><p>Your task will pass through five specialized agents in sequence.</p><div className="suggestions" onClick={() => setTask("Analyze the key risks and opportunities in launching a new subscription product.")}>Analyze product launch risks <AppIcon name="arrow"/></div></div>}{busy && <div className="progress-box" role="status" aria-live="polite"><div className="spinner"/><div><b>Agents are collaborating</b><p>Live stage updates from the API. Research may take longer while it searches the web.</p></div></div>}{(result || stages.some(stage => stage.output)) && <ResultsPanel output={result} stages={stages} workflowStatus={execution.state} />}</div><ExecutionNotice execution={execution} client={execution.client} onNew={() => { setTask(""); setStages([]); }} /><form className="composer" onSubmit={submit}><textarea value={task} onChange={e => setTask(e.target.value)} maxLength={1000} minLength={3} required aria-label="Task for agents" placeholder="Describe a task or paste context for your agents…"/><div className="composer-bottom"><small>{task.length}/1000 · Search configuration shown above · No arbitrary commands</small><button className="primary" disabled={busy || task.trim().length < 3}>{busy ? "Working…" : execution.submission ? "Retry same submission" : <>Run workflow <AppIcon name="arrow"/></>}</button></div></form></section><aside className="card workflow-summary"><h2>Workflow stages</h2><p>Updated from real stage events via SSE.</p>{["Orchestrator", "Research", "Analysis", "Report", "Review"].map((s, i) => { const stage = stages.find(item => item.agent === s); const status = stage?.status ?? (result ? "completed" : "pending"); return <div className="stage" key={s}><span className={`stage-number ${status === "completed" ? "done" : status === "running" ? "active" : ""}`}>{status === "completed" ? <AppIcon name="check"/> : i + 1}</span><div><b>{s}</b><small>{status}{stage?.retry ? ` · ${stage.retry}` : ""}{stage?.elapsed_ms != null ? ` · ${(stage.elapsed_ms / 1000).toFixed(1)}s` : ""}{stage?.error ? ` · ${stage.error}` : ""}</small></div>{i < 4 && <span className="stage-line"/>}</div>; })}<div className="approval-note"><b>Research sources</b><small>Google Search grounding is read-only. Sensitive action tools are not enabled.</small></div></aside></div></>}
        {section === "Agent Studio" && <AgentStudio />}
        {section === "Workflows" && <WorkflowBuilder />}
        {section === "Tasks & Execution" && <><PageHeading eyebrow="RUN LOG" title="Tasks & Execution" subtitle="Persistent task history with real stage state and usage."/>{apiError && <div className="notice error" role="alert">{apiError}</div>}{data?.history.length ? <section className="card table-card"><div className="table-head"><span aria-hidden="true"></span><span>Task</span><span>Status</span><span>Action</span></div>{data.history.map(run => <RunRow key={run.id} run={run} onDelete={() => void removeTask(run.id)}/>)}</section> : <section className="card empty"><span><AppIcon name="clock"/></span><b>{data ? "No runs recorded" : "Loading runs"}</b><small>{data ? "Run a workflow to see persisted task history." : "Fetching execution history…"}</small></section>}</>}
        {section === "Knowledge Base" && <><PageHeading eyebrow="KNOWLEDGE" title="Knowledge Base" subtitle="Connect reference material to your agents."/><section className="card empty"><span><AppIcon name="knowledge"/></span><b>Knowledge sources are not connected</b><small>File ingestion and persistent retrieval are planned for a future phase.</small><span className="planned">PLANNED</span></section></>}
        {section === "Reports" && <><PageHeading eyebrow="OUTPUTS" title="Reports" subtitle="Completed and partially completed workflow outputs."/>{reports.length ? <div className="report-list">{reports.map(report => <article className="card historical-result" key={report.id}><header><div><h2>{report.task}</h2><small>{report.status} · {new Date(report.created_at).toLocaleString()}{report.elapsed_ms != null ? ` · ${(report.elapsed_ms / 1000).toFixed(1)}s total` : ""}</small></div></header>{report.error && <div className="notice error" role="alert">{report.error}</div>}<ResultsPanel output={report.result} stages={report.stages ?? []} workflowStatus={report.status}/></article>)}</div> : <section className="card empty"><span><AppIcon name="reports"/></span><b>{data?.history.length ? "No saved workflow results found" : "No workflow results yet"}</b><small>Completed and partially completed agent outputs appear here.</small></section>}</>}
        <footer className="footer">AgentFlow AI <span>·</span> Workspace data reflects the current API process</footer>
      </div>
    </section>
  </main>;
}

function PageHeading({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div></div>; }
function RunRow({ run, onDelete }: { run: Run; onDelete?: () => void }) { return <div className="run-row"><span className="run-mark"><AppIcon name="sparkles"/></span><div className="run-title"><b>{run.task}</b><small>{new Date(run.created_at).toLocaleString()}{run.elapsed_ms != null ? ` · ${(run.elapsed_ms / 1000).toFixed(1)}s total` : ""}{run.total_tokens != null ? ` · ${run.total_tokens.toLocaleString()} tokens · $${run.estimated_cost?.toFixed(6) ?? "—"}` : ""}{run.error ? ` · ${run.error}` : ""}</small>{run.stages?.length ? <small>{run.stages.map(stage => `${stage.agent}: ${stage.status}${stage.elapsed_ms != null ? ` ${(stage.elapsed_ms / 1000).toFixed(1)}s` : ""}${stage.error && stage.status !== "failed" && stage.status !== "timed_out" ? "" : stage.error ? ` (${stage.error})` : ""}`).join(" · ")}</small> : null}</div><span className={`run-status ${run.status}`}>{run.status}</span>{onDelete && <button className="run-delete" type="button" onClick={onDelete} aria-label={`Delete task: ${run.task}`}>Delete</button>}</div>; }
