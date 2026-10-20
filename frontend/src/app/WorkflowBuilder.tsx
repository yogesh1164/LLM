"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "./api";
import { MarkdownContent } from "./ResultsPanel";
import "./workflow-builder.css";

type Agent = { id: string; name: string; provider: string; model: string; enabled: boolean };
type Definition = { id: string; name: string; description: string; enabled: boolean; agent_ids: string[]; created_at: string; updated_at: string };
type StepRun = { position: number; agent_name: string; provider: string; model: string; status: string; output: string | null; error: string | null; elapsed_ms: number | null; input_tokens: number | null; output_tokens: number | null };
type WorkflowRun = { id: string; workflow_id: string | null; workflow_name: string; task: string; status: string; result: string | null; error: string | null; created_at: string; completed_at: string | null; steps: StepRun[] };
type FormState = { name: string; description: string; enabled: boolean; agent_ids: string[] };
const blank: FormState = { name: "", description: "", enabled: true, agent_ids: [] };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg?: string }) => d.msg ?? "Invalid input").join("; ");
    } catch { /* Fall back to HTTP status. */ }
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export function WorkflowBuilder() {
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<"new" | string | null>(null);
  const [form, setForm] = useState<FormState>(blank);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selectedWorkflow, setSelectedWorkflow] = useState<Definition | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<WorkflowRun | null>(null);
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const [copyNotice, setCopyNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [workflows, savedAgents] = await Promise.all([
        request<Definition[]>("/api/custom-workflows"),
        request<Agent[]>("/api/agents"),
      ]);
      setDefinitions(workflows);
      setAgents(savedAgents);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load workflows.");
    } finally { setLoading(false); }
  }, []);

 useEffect(() => {
  const timer = window.setTimeout(() => {
    void load();
  }, 0);

  return () => window.clearTimeout(timer);
}, [load]);

  const loadRuns = useCallback(async (workflowId: string) => {
    setRunsLoading(true);
    setRunError("");
    try {
      const items = await request<WorkflowRun[]>(`/api/custom-workflows/${workflowId}/runs`);
      setRuns(items);
      setSelectedRun(items[0] ?? null);
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : "Could not load execution history.");
    } finally { setRunsLoading(false); }
  }, []);

  function openNew() { setForm({ ...blank, agent_ids: [] }); setEditor("new"); setError(""); }
  function openEdit(workflow: Definition) {
    setForm({ name: workflow.name, description: workflow.description, enabled: workflow.enabled, agent_ids: [...workflow.agent_ids] });
    setEditor(workflow.id);
    setError("");
  }
  function addAgent(id: string) {
    if (!id || form.agent_ids.includes(id) || form.agent_ids.length >= 5) return;
    setForm(previous => ({ ...previous, agent_ids: [...previous.agent_ids, id] }));
  }
  function removeAgent(index: number) { setForm(previous => ({ ...previous, agent_ids: previous.agent_ids.filter((_, i) => i !== index) })); }
  function moveAgent(index: number, offset: number) {
    const next = index + offset;
    if (next < 0 || next >= form.agent_ids.length) return;
    setForm(previous => {
      const ids = [...previous.agent_ids];
      [ids[index], ids[next]] = [ids[next], ids[index]];
      return { ...previous, agent_ids: ids };
    });
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true); setError(""); setNotice("");
    try {
      const isNew = editor === "new";
      const saved = await request<Definition>(isNew ? "/api/custom-workflows" : `/api/custom-workflows/${editor}`, {
        method: isNew ? "POST" : "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
      });
      setEditor(null);
      setNotice(`${isNew ? "Created" : "Updated"} ${saved.name}.`);
      await load();
      if (selectedWorkflow?.id === saved.id) setSelectedWorkflow(saved);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save workflow."); }
    finally { setSaving(false); }
  }
  async function deleteWorkflow(workflow: Definition) {
    if (!window.confirm(`Delete workflow "${workflow.name}" and its saved runs? This cannot be undone.`)) return;
    setBusyId(workflow.id); setError("");
    try {
      await request<void>(`/api/custom-workflows/${workflow.id}`, { method: "DELETE" });
      if (selectedWorkflow?.id === workflow.id) { setSelectedWorkflow(null); setRuns([]); setSelectedRun(null); }
      setNotice(`Deleted ${workflow.name}.`);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not delete workflow."); }
    finally { setBusyId(null); }
  }
  function inspect(workflow: Definition) {
    setSelectedWorkflow(workflow); setSelectedRun(null); setRuns([]); setTask("");
    void loadRuns(workflow.id);
  }
  async function execute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkflow || running || !task.trim()) return;
    setRunning(true); setRunError("");
    try {
      const result = await request<WorkflowRun>(`/api/custom-workflows/${selectedWorkflow.id}/execute`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task: task.trim() }),
      });
      setSelectedRun(result);
      await loadRuns(selectedWorkflow.id);
      setSelectedRun(result);
      setTask("");
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : "Workflow execution failed.");
      await loadRuns(selectedWorkflow.id);
    } finally { setRunning(false); }
  }
  const configuredModelAgents = agents.filter(agent => agent.enabled && agent.provider === "gemini");
  const availableAgents = configuredModelAgents.filter(agent => !form.agent_ids.includes(agent.id));
  const selectedCanRun = selectedWorkflow?.enabled && selectedWorkflow.agent_ids.every(id => configuredModelAgents.some(agent => agent.id === id));

  return <section className="workflow-builder" aria-label="Custom workflow builder">
    <div className="wb-intro"><div><div className="eyebrow">CUSTOM ORCHESTRATION</div><h1>Workflow Builder</h1><p>Connect up to five custom Gemini agents in order. The original five-stage workflow is unchanged.</p></div>
      <button className="primary" type="button" onClick={openNew}>Create workflow</button></div>
    {notice && <div className="studio-notice" role="status">{notice}</div>}
    {error && <div className="notice error" role="alert">{error} <button type="button" className="studio-action" onClick={() => void load()}>Retry</button></div>}
    <div className="wb-fixed card"><strong>Built-in workflow (protected)</strong><p>Orchestrator → Research → Analysis → Report → Review</p><small>Continue running this from AI Workspace.</small></div>
    {editor !== null && <form className="card wb-editor" onSubmit={event => void save(event)}>
      <div className="wb-row"><h2>{editor === "new" ? "Create custom workflow" : "Edit custom workflow"}</h2><button className="studio-action" type="button" onClick={() => setEditor(null)}>Close</button></div>
      <div className="wb-fields"><label>Name<input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label>Description<textarea maxLength={1000} rows={2} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
        <label className="wb-check"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> Enabled</label></div>
      <h3>Execution order ({form.agent_ids.length}/5)</h3>
      {form.agent_ids.length === 0 ? <p className="wb-muted">Add an enabled Gemini agent to begin.</p> :
        <ol className="wb-steps">{form.agent_ids.map((id, index) => <li key={id}>
          <div><strong>{index + 1}. {agents.find(a => a.id === id)?.name ?? "Missing agent"}</strong><small>Output passes to the next step</small></div>
          <div className="wb-controls"><button type="button" className="studio-action" disabled={index === 0} onClick={() => moveAgent(index, -1)} aria-label={`Move step ${index + 1} up`}>↑</button>
          <button type="button" className="studio-action" disabled={index === form.agent_ids.length - 1} onClick={() => moveAgent(index, 1)} aria-label={`Move step ${index + 1} down`}>↓</button>
          <button type="button" className="studio-action destructive" onClick={() => removeAgent(index)} aria-label={`Remove step ${index + 1}`}>Remove</button></div>
        </li>)}</ol>}
      <label className="wb-add-label">Add agent <select value="" onChange={event => addAgent(event.target.value)} disabled={form.agent_ids.length >= 5 || availableAgents.length === 0}>
        <option value="">Select enabled Gemini agent…</option>{availableAgents.map(agent => <option key={agent.id} value={agent.id}>{agent.name} ({agent.model})</option>)}
      </select></label>
      {configuredModelAgents.length === 0 && <p className="wb-muted">Create an enabled Gemini agent in Agent Studio first.</p>}
      <div className="wb-actions"><button type="button" className="secondary" onClick={() => setEditor(null)}>Cancel</button><button type="submit" className="primary" disabled={saving || !form.name.trim() || form.agent_ids.length === 0}>{saving ? "Saving…" : "Save workflow"}</button></div>
    </form>}
    <div className="wb-row wb-heading"><h2>Saved custom workflows</h2><span>{definitions.length} workflow{definitions.length === 1 ? "" : "s"}</span></div>
    {loading ? <p role="status" className="wb-muted">Loading workflows…</p> : definitions.length === 0 ? <div className="card wb-empty">No saved custom workflows yet. Create your first workflow above.</div> :
      <div className="wb-grid">{definitions.map(workflow => <article className="card wb-card" key={workflow.id}>
        <div className="wb-row"><h3>{workflow.name}</h3><span className={workflow.enabled ? "wb-enabled" : "wb-disabled"}>{workflow.enabled ? "Enabled" : "Disabled"}</span></div>
        <p>{workflow.description || "No description provided."}</p>
        <ol>{workflow.agent_ids.map((id, index) => <li key={id}>{index + 1}. {agents.find(agent => agent.id === id)?.name ?? "Deleted agent"}</li>)}</ol>
        <div className="wb-card-actions"><button type="button" className="studio-action" onClick={() => inspect(workflow)}>View / Run</button><button type="button" className="studio-action" onClick={() => openEdit(workflow)}>Edit</button>
          <button type="button" className="studio-action destructive" disabled={busyId === workflow.id || running} onClick={() => void deleteWorkflow(workflow)}>Delete</button></div>
      </article>)}</div>}
    {selectedWorkflow && <section className="card wb-run-panel" aria-label="Workflow execution and history">
      <div className="wb-row"><div><h2>{selectedWorkflow.name}</h2><p>Execution history and step-by-step results</p></div><button type="button" className="studio-action" disabled={running} onClick={() => setSelectedWorkflow(null)}>Close</button></div>
      <form className="wb-run-form" onSubmit={event => void execute(event)}><label>Task<textarea required minLength={3} maxLength={8000} rows={3} value={task} disabled={running} onChange={e => setTask(e.target.value)} placeholder="Describe the task for this workflow…" /></label>
        <div className="wb-row"><small>{task.length}/8000 characters · Running uses your Gemini API quota.</small><button className="primary" type="submit" disabled={!selectedCanRun || running || task.trim().length < 3}>{running ? "Running workflow…" : "Run workflow"}</button></div>
        {!selectedCanRun && <p className="wb-warning">Enable the workflow and all assigned Gemini agents to run it. Their models must match the configured backend model.</p>}</form>
      {running && <p role="status" className="wb-muted">Running sequential agents. Keep this page open.</p>}
      {runError && <div className="notice error" role="alert">{runError}</div>}
      <div className="wb-history-layout"><aside className="wb-history"><h3>Previous runs</h3>{runsLoading ? <p>Loading…</p> : runs.length === 0 ? <p>No runs yet.</p> : runs.map(run => <button key={run.id} type="button" className={selectedRun?.id === run.id ? "selected" : ""} onClick={() => { setSelectedRun(run); setCopyNotice(""); }}><strong>{run.status}</strong><span>{new Date(run.created_at).toLocaleString()}</span><small>{run.task}</small></button>)}</aside>
        <div className="wb-run-results"><h3>Execution results</h3>{selectedRun ? <>
          <p><strong>Status:</strong> {selectedRun.status}</p>{selectedRun.error && <div className="notice error" role="alert">{selectedRun.error}</div>}
          {selectedRun.steps.map(step => <div className="wb-result-step" key={step.position}><div className="wb-row"><h4>{step.position + 1}. {step.agent_name}</h4><span>{step.status}</span></div>
            <div className="wb-step-meta">{step.elapsed_ms != null && <span>{(step.elapsed_ms / 1000).toFixed(1)}s</span>}{step.input_tokens != null && <span>{step.input_tokens} input tokens</span>}{step.output_tokens != null && <span>{step.output_tokens} output tokens</span>}</div>
            {step.error && <p role="alert" className="wb-warning">{step.error}</p>}
            {step.output && <><button type="button" className="studio-action" onClick={() => void navigator.clipboard.writeText(step.output ?? "").then(() => setCopyNotice(`Copied ${step.agent_name} output`)).catch(() => setCopyNotice("Could not copy output"))}>Copy output</button><MarkdownContent source={step.output}/></>}
          </div>)}{copyNotice && <p role="status">{copyNotice}</p>}
        </> : <p className="wb-muted">Choose a previous run to inspect its stages.</p>}</div></div>
    </section>}
  </section>;
}
