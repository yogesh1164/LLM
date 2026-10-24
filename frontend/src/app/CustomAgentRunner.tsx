"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "./api";
import { useDurableExecution } from "./useDurableExecution";
import { ExecutionNotice } from "./ExecutionNotice";
import { MarkdownContent } from "./ResultsPanel";
import "./custom-agent-runner.css";

type Execution = {
  id: string;
  agent_id: string;
  task: string;
  status: string;
  result?: string | null;
  error?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  elapsed_ms?: number | null;
  created_at: string;
  completed_at?: string | null;
};

export type RunAgent = {
  id: string;
  name: string;
  provider: string;
  enabled: boolean;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) message = body.detail;
    } catch { /* Keep the HTTP status message. */ }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function CustomAgentRunner({ agent, onClose }: { agent: RunAgent; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [task, setTask] = useState("");
  const [history, setHistory] = useState<Execution[]>([]);
  const [historySelection, setSelected] = useState<Execution | null>(null);
  const execution = useDurableExecution<Execution>(`/api/agents/${agent.id}/execute`);
  const selected = execution.data ?? historySelection;
  const [historyLoading, setHistoryLoading] = useState(true);
  const running = execution.busy;
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const items = await requestJson<Execution[]>(`/api/agents/${agent.id}/executions`);
      setHistory(items);
      setSelected((previous) => items.find((item) => item.id === previous?.id) ?? items[0] ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load execution history.");
    } finally {
      setHistoryLoading(false);
    }
  }, [agent.id]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    void loadHistory();
    // Do not call dialog.close() in effect cleanup. React Strict Mode may
    // replay effects in development, and close() fires onClose, which unmounts
    // the runner immediately after opening it.
  }, [loadHistory]);

  async function execute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!agent.enabled || agent.provider !== "gemini" || !task.trim() || execution.client.getSnapshot().busy) return;
    setError("");
    try {
      const result = await execution.client.submit(task.trim());
      if (result?.status === "completed") setTask("");
      await loadHistory();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent execution failed.");
      await loadHistory();
    }
  }

  async function copyOutput() {
    if (!selected?.result) return;
    try {
      await navigator.clipboard.writeText(selected.result);
      setCopied(true);
    } catch {
      setError("Could not copy output to clipboard.");
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="custom-runner-dialog"
      aria-labelledby="custom-runner-title"
      onCancel={(event) => { if (running) event.preventDefault(); }}
      onClose={onClose}
    >
      <div className="custom-runner-content">
        <header className="custom-runner-header">
          <div><div className="eyebrow">CUSTOM AGENT EXECUTION</div><h2 id="custom-runner-title">Run {agent.name}</h2></div>
          <button type="button" className="studio-action" onClick={() => dialogRef.current?.close()} disabled={running}>Close</button>
        </header>
        <form onSubmit={(event) => void execute(event)} className="custom-runner-form">
          <label htmlFor="custom-runner-task">Task for this agent</label>
          <textarea id="custom-runner-task" value={task} onChange={(event) => setTask(event.target.value)}
            rows={4} maxLength={8000} required placeholder="Describe what this agent should do..." disabled={running} />
          <div className="custom-runner-actions">
            <span>{task.length}/8000 characters</span>
            <button className="primary" type="submit"
              disabled={running || !task.trim() || !agent.enabled || agent.provider !== "gemini"}>
              {running ? "Running agent..." : execution.submission ? "Retry same submission" : "Run agent"}
            </button>
          </div>
          {agent.provider !== "gemini" && <p className="custom-runner-warning">Custom-agent execution currently supports Gemini only.</p>}
          {!agent.enabled && <p className="custom-runner-warning">Enable this agent before running it.</p>}
        </form>
        <ExecutionNotice execution={execution} client={execution.client} onNew={() => setTask("")} />
        {error && <div role="alert" className="notice error">{error}</div>}
        {running && <p role="status" className="custom-runner-running">Agent is running. Keep this window open.</p>}
        <div className="custom-runner-layout">
          <section className="custom-runner-history" aria-label="Previous executions">
            <h3>Execution history</h3>
            {historyLoading ? <p>Loading history...</p> : history.length === 0 ? <p>No previous executions.</p> : (
              <div className="custom-runner-history-items">
                {history.map((item) => (
                  <button type="button" key={item.id} className={selected?.id === item.id ? "selected" : ""}
                    onClick={() => { execution.client.clearResult(); setSelected(item); setCopied(false); }}>
                    <span>{new Date(item.created_at).toLocaleString()}</span>
                    <strong>{item.status}</strong>
                    <small>{item.task}</small>
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="custom-runner-result" aria-label="Execution result">
            <div className="custom-runner-result-heading">
              <h3>Result</h3>
              <button type="button" className="studio-action" disabled={!selected?.result}
                onClick={() => void copyOutput()}>{copied ? "Copied" : "Copy output"}</button>
            </div>
            {selected ? (
              <>
                <div className="custom-runner-meta">
                  <span>Status: {selected.status}</span>
                  {selected.elapsed_ms != null && <span>{(selected.elapsed_ms / 1000).toFixed(1)}s</span>}
                  {selected.input_tokens != null && <span>{selected.input_tokens} input tokens</span>}
                  {selected.output_tokens != null && <span>{selected.output_tokens} output tokens</span>}
                </div>
                {selected.error && <div role="alert" className="notice error">{selected.error}</div>}
                {selected.result ? <MarkdownContent source={selected.result} /> : <p>No output was saved for this execution.</p>}
              </>
            ) : <p>Choose an execution from history or run the agent.</p>}
          </section>
        </div>
      </div>
    </dialog>
  );
}
