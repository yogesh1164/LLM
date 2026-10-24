"use client";

import { ExecutionClient, executionLabel, type ExecutionSnapshot } from "./execution-client";

export function ExecutionNotice({ execution, client, onNew }: { execution: Omit<ExecutionSnapshot, "data">; client: ExecutionClient; onNew: () => void }) {
  if (execution.state === "idle" && !execution.error) return null;
  const newExecution = () => {
    if (execution.state !== "completed" && !window.confirm("Review saved history first. A new execution uses a different submission identifier and may duplicate paid work. Start a separate new execution?")) return;
    client.newIntent(); onNew();
  };
  return <div className="notice execution-notice" aria-label="Submission status">
    <p role="status" aria-live="polite"><strong>{executionLabel(execution.state)}</strong>{execution.submission?.executionId && <> · Execution {execution.submission.executionId}</>}</p>
    {execution.error && <p role="alert">{execution.error}</p>}
    {execution.state === "unknown" && !execution.submission?.executionId && <p>Retry uses the saved submission identifier. Re-enter the exact original task; do not start new work to check its status.</p>}
    {execution.state === "expired" && <p>Old client identity has expired. Inspect server history before starting new work.</p>}
    <div className="execution-actions">
      {execution.submission?.executionId && <button type="button" className="studio-action" disabled={execution.busy} onClick={() => void client.check()}>Check status</button>}
      {execution.busy && <button type="button" className="studio-action" onClick={client.stop}>Stop monitoring</button>}
      <button type="button" className="studio-action" disabled={execution.busy} onClick={newExecution}>New execution</button>
    </div>
  </div>;
}
