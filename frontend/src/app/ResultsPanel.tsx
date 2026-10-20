"use client";

import { KeyboardEvent, useId, useRef, useState } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

export type AgentStage = {
  agent: string;
  status: string;
  output?: string | null;
  error?: string | null;
  elapsed_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
};

export type AgentOutput = {
  orchestrator?: string;
  plan?: string;
  research?: string;
  analysis?: string;
  report?: string;
  review?: string;
  sources?: { url: string; title?: string | null }[];
  total_tokens?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  estimated_cost?: number | null;
};

const agents = ["Report", "Review", "Research", "Analysis", "Orchestrator"] as const;
type Agent = (typeof agents)[number];

export function ResultsPanel({
  output,
  stages,
  workflowStatus,
}: {
  output?: AgentOutput | null;
  stages: AgentStage[];
  workflowStatus: string;
}) {
  const [selected, setSelected] = useState<Agent>("Report");
  const [copied, setCopied] = useState(false);
  const baseId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = agents.indexOf(selected);
  const stage = stages.find((item) => item.agent === selected);
  const stageOutput = selected === "Orchestrator" ? output?.orchestrator ?? output?.plan : output?.[selected.toLowerCase() as "report" | "review" | "research" | "analysis"];
  const text = stage?.output ?? stageOutput ?? "";
  const status = stage?.status ?? (text ? "completed" : "pending");
  const panelId = (agent: Agent) => `${baseId}-${agent.toLowerCase()}`;
  const tabId = (agent: Agent) => `${panelId(agent)}-tab`;

  function handleTabKey(event: KeyboardEvent<HTMLDivElement>) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % agents.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + agents.length) % agents.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = agents.length - 1;
    else return;
    event.preventDefault();
    const agent = agents[next];
    setSelected(agent);
    tabRefs.current[next]?.focus();
  }

  async function copyOutput() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  const stageTokens = stage?.input_tokens != null || stage?.output_tokens != null
    ? `${(stage.input_tokens ?? 0) + (stage.output_tokens ?? 0)} tokens`
    : null;

  return (
    <section className="agent-results" aria-label="Workflow results">
      <div className={`results-state ${workflowStatus === "completed" ? "success" : "partial"}`}>
        <span className="results-state-dot" />
        <span>{workflowStatus === "completed" ? "Workflow completed" : workflowStatus === "failed" ? "Workflow stopped · completed outputs are available" : "Workflow results"}</span>
        {output?.total_tokens != null && <span className="results-total">{output.total_tokens.toLocaleString()} total tokens</span>}
        {output?.estimated_cost != null && <span className="results-total">${output.estimated_cost.toFixed(6)} estimated</span>}
      </div>
      <div className="agent-tabs" role="tablist" aria-label="Agent output" onKeyDown={handleTabKey}>
        {agents.map((agent, tabIndex) => {
          const item = stages.find((candidate) => candidate.agent === agent);
          const agentText = agent === "Orchestrator"
            ? item?.output ?? output?.orchestrator ?? output?.plan
            : item?.output ?? output?.[agent.toLowerCase() as "report" | "review" | "research" | "analysis"];
          const agentStatus = item?.status ?? (agentText ? "completed" : "pending");
          return (
            <button
              key={agent}
              ref={(element) => { tabRefs.current[tabIndex] = element; }}
              type="button"
              role="tab"
              id={tabId(agent)}
              aria-selected={selected === agent}
              aria-controls={panelId(agent)}
              tabIndex={selected === agent ? 0 : -1}
              className={`agent-tab ${selected === agent ? "selected" : ""}`}
              onClick={() => { setSelected(agent); setCopied(false); }}
            >
              <span>{agent}</span>
              <span className={`agent-tab-status ${agentStatus}`}>{agentStatus === "completed" ? "Ready" : agentStatus}</span>
            </button>
          );
        })}
      </div>
      <div className="agent-output-card" role="tabpanel" id={panelId(selected)} aria-labelledby={tabId(selected)} tabIndex={0}>
        <div className="agent-output-heading">
          <div>
            <h2>{selected}</h2>
            <div className="agent-output-meta">
              <span className={`meta-status ${status}`}>{status}</span>
              {stage?.elapsed_ms != null && <span>{(stage.elapsed_ms / 1000).toFixed(1)}s</span>}
              {stageTokens && <span>{stageTokens}</span>}
              {(stage?.input_tokens != null || stage?.output_tokens != null) && <span>{stage?.input_tokens ?? 0} in · {stage?.output_tokens ?? 0} out</span>}
            </div>
          </div>
          <button className="copy-output" type="button" onClick={copyOutput} disabled={!text} aria-label={`Copy ${selected} output`}>
            {copied ? "Copied" : "Copy output"}
          </button>
        </div>
        {stage?.error && <div className="notice error" role="alert">{stage.error}</div>}
        {text
          ? <MarkdownContent source={text} />
          : <div className="agent-output-empty">{status === "pending" || status === "running" ? "This agent has not finished yet." : "No output was saved for this stage."}</div>}
        {selected === "Research" && output?.sources?.length ? (
          <div className="research-sources">
            <h3>Research sources</h3>
            <ul>{output.sources.map((source) => (
              <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title || source.url}</a></li>
            ))}</ul>
          </div>
        ) : null}
      </div>
      <span className="sr-only" aria-live="polite">{copied ? `${selected} output copied` : ""}</span>
    </section>
  );
}

const markdownComponents: Components = {
  h1: ({ children }) => <h1 className="md-heading md-h1">{children}</h1>,
  h2: ({ children }) => <h2 className="md-heading md-h2">{children}</h2>,
  h3: ({ children }) => <h3 className="md-heading md-h3">{children}</h3>,
  h4: ({ children }) => <h4 className="md-heading md-h4">{children}</h4>,
  h5: ({ children }) => <h5 className="md-heading md-h5">{children}</h5>,
  h6: ({ children }) => <h6 className="md-heading md-h6">{children}</h6>,
  p: ({ children }) => <p className="md-paragraph">{children}</p>,
  ul: ({ children }) => <ul className="md-list">{children}</ul>,
  ol: ({ children }) => <ol className="md-list">{children}</ol>,
  blockquote: ({ children }) => <blockquote className="md-quote">{children}</blockquote>,
  pre: ({ children }) => <pre className="md-code">{children}</pre>,
  code: ({ className, children }) => <code className={className ? undefined : "md-inline-code"}>{children}</code>,
  table: ({ children }) => <div className="md-table-wrap"><table className="md-table">{children}</table></div>,
  a: ({ href, title, children }) => {
    const external = Boolean(href && /^https?:\/\//i.test(href));
    return <a href={href} title={title} target={external ? "_blank" : undefined} rel={external ? "noopener noreferrer" : undefined}>{children}</a>;
  },
};

function safeMarkdownUrl(url: string) {
  // Keep web links and local anchors/paths; reject script, data, and other protocols.
  if (/^(https?:\/\/|mailto:)/i.test(url) || /^\/(?!\/)/.test(url) || url.startsWith("#")) return url;
  return "";
}

function MarkdownContent({ source }: { source: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml urlTransform={safeMarkdownUrl} components={markdownComponents}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
