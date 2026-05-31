import { useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  Brain,
  Calculator,
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  FlaskConical,
  GitBranch,
  GitPullRequest,
  Loader2,
  SearchCode,
  ShieldAlert
} from "lucide-react";
import { apiBase } from "../api";
import type { AgentEvent, AgentFinding } from "../types";
import FindingCard from "./FindingCard";

interface Props {
  events: AgentEvent[];
  findings: AgentFinding[];
  activeAgent: string | null;
  disabled: boolean;
  onRunAgent: (agentName: string) => void;
  onGenerateCode: () => void;
}

type AssistantAction = {
  agent: string;
  label: string;
  icon: typeof GitPullRequest;
  detail: string;
  tone: string;
};

type WorkProduct = {
  id: string;
  agent: string;
  title: string;
  body: string;
  href?: string;
  badge?: string;
  canGenerateCode?: boolean;
};

const assistantActions: AssistantAction[] = [
  { agent: "reference", label: "Explain citations", icon: GitPullRequest, detail: "Connect the first citation to this paper", tone: "reference" },
  { agent: "critique", label: "Review claims", icon: ShieldAlert, detail: "Surface weak baselines and missing checks", tone: "critique" },
  { agent: "code", label: "Find implementation", icon: SearchCode, detail: "Look for code that matches the paper", tone: "code" },
  { agent: "math", label: "Explain math", icon: Calculator, detail: "Explain equations and audit notation", tone: "math" },
  { agent: "replication", label: "Plan replication", icon: FlaskConical, detail: "Create a lightweight reproduction scorecard", tone: "replication" },
  { agent: "evaluation", label: "Improve evaluation", icon: Activity, detail: "Suggest benchmarks and metrics", tone: "evaluation" },
  { agent: "graph", label: "Refresh map", icon: GitBranch, detail: "Sync the research map", tone: "graph" }
];

function AgentPanel({ events, findings, activeAgent, disabled, onRunAgent, onGenerateCode }: Props) {
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const latest = [...events].reverse();
  const active = assistantActions.find((action) => action.agent === activeAgent);
  const selectedAction = selectedTask ? assistantActions.find((action) => action.agent === selectedTask) : null;
  const recentActivity = latest.map(toActivity).filter((event): event is AgentEvent => event !== null).slice(0, 4);
  const products = buildWorkProducts(events).slice(0, 4);
  const technicalEvents = latest.slice(0, 14);

  if (selectedAction) {
    return (
      <TaskDetailPanel
        action={selectedAction}
        activeAgent={activeAgent}
        disabled={disabled}
        events={events}
        findings={findings}
        onBack={() => setSelectedTask(null)}
        onRunAgent={onRunAgent}
        onGenerateCode={onGenerateCode}
      />
    );
  }

  return (
    <div className="panel agent-panel">
      <div className="panel-title">
        <Brain size={16} />
        <span>Research Assistants</span>
      </div>
      <div className={`agent-runner ${active ? "is-running" : ""}`}>
        <strong>{active ? active.label : latest[0] ? "Paper workspace ready" : "No paper loaded"}</strong>
        <span>{active ? active.detail : latest[0] ? humanizeEvent(latest[0]) : "Load an arXiv link or upload a paper."}</span>
      </div>
      <div className="agent-grid">
        {assistantActions.map(({ agent, label, icon: Icon, tone }) => {
          const isActive = activeAgent === agent;
          const status = isActive ? "running" : inferStatus(agent, latest);
          return (
            <button
              key={agent}
              className={`agent-card action-${tone} status-${status}`}
              disabled={disabled}
              onClick={() => {
                setSelectedTask(agent);
                onRunAgent(agent);
              }}
            >
              <Icon size={16} />
              <span className="agent-name">{label}</span>
              <ChevronRight className="agent-arrow" size={16} />
              {isActive && (
                <span className="agent-card-loader">
                  <Loader2 className="spin" size={12} />
                  Generating
                </span>
              )}
            </button>
          );
        })}
      </div>
      {active && <GenerationRow action={active} />}
      <div className="feed-section">
        <h3>Results</h3>
        <div className="result-list">
          {products.map((product) => (
            <div className="result-card" key={product.id}>
              <BookOpen size={14} />
              <div>
                <strong>{product.title}</strong>
                <p>{product.body}</p>
                {product.href && (
                  <a href={product.href} target="_blank" rel="noreferrer">
                    {product.agent === "code" && product.title.includes(".zip") ? "Download ZIP" : "Open source"}
                  </a>
                )}
                {product.canGenerateCode && (
                  <button className="inline-action-button" type="button" disabled={disabled} onClick={onGenerateCode}>
                    <Download size={13} />
                    Generate code ZIP
                  </button>
                )}
                {product.badge && <span className="result-badge">{product.badge}</span>}
              </div>
            </div>
          ))}
          {products.length === 0 && <div className="empty-feed">Results will appear here.</div>}
        </div>
      </div>
      <div className="feed-section">
        <h3>Recent Activity</h3>
        <div className="activity-list">
          {recentActivity.map((event) => (
            <div className="activity-row" key={event.id}>
              <span>{event.agent}</span>
              <p>{event.message}</p>
              <small>{formatTime(event.timestamp)}</small>
            </div>
          ))}
          {recentActivity.length === 0 && <div className="empty-feed">Waiting for activity.</div>}
        </div>
      </div>
      <div className="feed-section">
        <h3>Insights</h3>
        <div className="finding-list">
          {findings.slice(-5).reverse().map((finding) => <FindingCard key={finding.id} finding={finding} />)}
          {findings.length === 0 && <div className="empty-feed">No insights yet.</div>}
        </div>
      </div>
      <details className="technical-log">
        <summary>
          <ChevronDown size={14} />
          <span>Technical log</span>
        </summary>
        <div className="event-feed">
          {technicalEvents.map((event) => (
            <div className="event-row" key={event.id}>
              <div>
                <span className="event-type">{event.type}</span>
                <p>{event.message}</p>
              </div>
              <small>{event.agent ?? "System"}</small>
            </div>
          ))}
          {technicalEvents.length === 0 && <div className="empty-feed">No events yet.</div>}
        </div>
      </details>
    </div>
  );
}

function TaskDetailPanel({
  action,
  activeAgent,
  disabled,
  events,
  findings,
  onBack,
  onRunAgent,
  onGenerateCode
}: {
  action: AssistantAction;
  activeAgent: string | null;
  disabled: boolean;
  events: AgentEvent[];
  findings: AgentFinding[];
  onBack: () => void;
  onRunAgent: (agentName: string) => void;
  onGenerateCode: () => void;
}) {
  const latest = [...events].reverse();
  const Icon = action.icon;
  const status = activeAgent === action.agent ? "running" : inferStatus(action.agent, latest);
  const agentEvents = latest.filter((event) => eventBelongsToAgent(event, action.agent)).slice(0, 8);
  const products = buildWorkProducts(events).filter((product) => product.agent === action.agent).slice(0, 6);
  const relatedFindings = findings.filter((finding) => finding.agent.toLowerCase().includes(action.agent)).slice(-4).reverse();

  return (
    <div className="panel agent-panel agent-detail-panel">
      <div className="agent-detail-nav">
        <button className="icon-button" type="button" onClick={onBack} aria-label="Back to research assistants">
          <ArrowLeft size={16} />
        </button>
        <span>Research Assistants</span>
        <ChevronRight size={14} />
        <strong>{action.label}</strong>
      </div>
      <div className={`agent-detail-hero action-${action.tone} status-${status}`}>
        <Icon size={24} />
        <div>
          <span className="status-pill">{statusLabel(status)}</span>
          <h2>{action.label}</h2>
          <p>{action.detail}</p>
        </div>
        <button className="task-run-button" type="button" disabled={disabled} onClick={() => onRunAgent(action.agent)}>
          {status === "running" ? <Loader2 className="spin" size={15} /> : <ChevronRight size={15} />}
          {status === "running" ? "Generating" : "Run"}
        </button>
      </div>
      {status === "running" && <GenerationRow action={action} compact />}
      <div className="agent-detail-body">
        <DetailSection title="Results" empty="This assistant has not produced a result yet.">
          {products.map((product) => (
            <div className="detail-result-card" key={product.id}>
              <BookOpen size={15} />
              <div>
                <strong>{product.title}</strong>
                <p>{product.body}</p>
                {product.href && (
                  <a href={product.href} target="_blank" rel="noreferrer">
                    <ExternalLink size={13} />
                    {product.title.includes(".zip") ? "Download ZIP" : "Open source"}
                  </a>
                )}
                {product.canGenerateCode && (
                  <button className="inline-action-button" type="button" disabled={disabled} onClick={onGenerateCode}>
                    <Download size={13} />
                    Generate code ZIP
                  </button>
                )}
                {product.badge && <span className="result-badge">{product.badge}</span>}
              </div>
            </div>
          ))}
        </DetailSection>
        <DetailSection title="Activity" empty="No activity for this assistant yet.">
          {agentEvents.map((event) => (
            <div className="detail-activity-row" key={event.id}>
              <span>{formatTime(event.timestamp)}</span>
              <div>
                <strong>{event.type}</strong>
                <p>{event.message}</p>
              </div>
            </div>
          ))}
        </DetailSection>
        <DetailSection title="Insights" empty="No saved insights from this assistant yet.">
          {relatedFindings.map((finding) => <FindingCard key={finding.id} finding={finding} />)}
        </DetailSection>
      </div>
    </div>
  );
}

function DetailSection({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <section className="agent-detail-section">
      <h3>{title}</h3>
      <div className="agent-detail-list">{hasChildren ? children : <div className="empty-feed">{empty}</div>}</div>
    </section>
  );
}

function GenerationRow({ action, compact = false }: { action: AssistantAction; compact?: boolean }) {
  return (
    <div className={`generation-row action-${action.tone} ${compact ? "is-compact" : ""}`}>
      <Loader2 className="spin" size={18} />
      <div>
        <strong>Generating {action.label}...</strong>
        <span>Based on the current paper workspace.</span>
      </div>
    </div>
  );
}

function inferStatus(agent: string, latest: AgentEvent[]) {
  const aliases: Record<string, string[]> = {
    reference: ["reference"],
    critique: ["critique"],
    code: ["code"],
    math: ["math"],
    replication: ["replication"],
    evaluation: ["evaluation"],
    graph: ["graph"]
  };
  const names = aliases[agent] ?? [agent];
  const event = latest.find((item) => names.includes(item.agent?.toLowerCase() ?? ""));
  if (!event) return "idle";
  if (event.status === "running") return "running";
  if (event.status === "failed") return "failed";
  if (event.status === "flagged" || event.type.includes("finding") || event.type.includes("missing") || event.type.includes("attack")) return "flagged";
  if (event.status === "done" || event.type === "agent.finished") return "done";
  return event.status ?? "done";
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    idle: "Ready",
    running: "Generating",
    done: "Done",
    failed: "Failed",
    flagged: "Needs review"
  };
  return labels[status] ?? status;
}

function eventBelongsToAgent(event: AgentEvent, agent: string) {
  const eventAgent = event.agent?.toLowerCase() ?? "";
  if (eventAgent.includes(agent)) return true;
  if (eventAgent) return false;
  const typeAliases: Record<string, string[]> = {
    reference: ["citation.resolving", "citation.resolved"],
    critique: ["critique.finding", "experiment.missing"],
    code: ["repo.ready", "code.generation_available", "codegen.started", "codegen.progress", "codegen.done"],
    math: ["math.issue"],
    replication: ["replication.queued"],
    evaluation: ["evaluation.plan", "benchmark.suggested", "experiment.missing"],
    graph: ["node.update", "edge.update"]
  };
  return typeAliases[agent]?.includes(event.type) ?? false;
}

function buildWorkProducts(events: AgentEvent[]) {
  const products: WorkProduct[] = [];
  [...events].reverse().forEach((event) => {
    const payload = event.payload ?? {};
    if (event.type === "citation.resolved") {
      const summary = payload.summary as { relationship?: string; why_it_matters_for_main_paper?: string } | undefined;
      products.push({
        id: event.id,
        agent: "reference",
        title: "Citation explained",
        body: summary?.why_it_matters_for_main_paper || summary?.relationship || event.message
      });
    }
    if (event.type === "repo.ready") {
      const repo = payload.repo as { full_name?: string; html_url?: string; match_reason?: string } | undefined;
      const confidence = payload.implementation_confidence as
        | { confidence?: number; verdict?: string; rationale?: string; recommend_generate?: boolean }
        | undefined;
      const score = typeof confidence?.confidence === "number" ? confidence.confidence : null;
      const bodyParts = [
        confidence?.rationale,
        repo?.match_reason,
      ].filter(Boolean);
      products.push({
        id: event.id,
        agent: "code",
        title: repo?.full_name || "Implementation found",
        body: bodyParts.join(" ") || "A candidate implementation repository is ready.",
        href: repo?.html_url,
        badge: score !== null ? `${Math.round(score * 100)}% ${confidence?.verdict ?? "confidence"}` : undefined,
        canGenerateCode: Boolean(confidence?.recommend_generate) || (score !== null && score < 0.65)
      });
    }
    if (event.type === "code.generation_available") {
      const confidence = payload.implementation_confidence as { confidence?: number; rationale?: string } | undefined;
      products.push({
        id: event.id,
        agent: "code",
        title: "Generated project available",
        body: confidence?.rationale || event.message,
        badge: typeof confidence?.confidence === "number" ? `${Math.round(confidence.confidence * 100)}% match` : undefined,
        canGenerateCode: true
      });
    }
    if (event.type === "codegen.done") {
      const downloadUrl = typeof payload.download_url === "string" ? `${apiBase()}${payload.download_url}` : undefined;
      products.push({
        id: event.id,
        agent: "code",
        title: `${String(payload.project_name || "generated-project")}.zip`,
        body: `${String(payload.file_count || "Multi-file")} files generated. ${String(payload.total_lines || "")} lines ready to download.`.trim(),
        href: downloadUrl
      });
    }
    if (event.type === "replication.queued") {
      products.push({
        id: event.id,
        agent: "replication",
        title: "Replication plan",
        body: String(payload.claim_under_test || payload.status || "A dry-run replication scorecard is ready.")
      });
    }
    if (event.type === "math.issue") {
      products.push({
        id: event.id,
        agent: "math",
        title: String(payload.title || "Math issue"),
        body: String(payload.description || event.message)
      });
    }
    if (event.type === "paper.stored") {
      products.push({
        id: event.id,
        agent: "parser",
        title: "Upload saved",
        body: String(payload.public_id || "Original paper stored."),
        href: typeof payload.secure_url === "string" ? payload.secure_url : undefined
      });
    }
    if (event.type === "paper.storage_failed") {
      products.push({
        id: event.id,
        agent: "parser",
        title: "Paper parsed locally",
        body: "Original-file storage was skipped, but the paper is ready to read."
      });
    }
    if (event.type === "benchmark.suggested") {
      const finding = payload as { title?: string; body?: string; severity?: string };
      products.push({ id: event.id, agent: "evaluation", title: finding.title || "Benchmark suggestion", body: finding.body || event.message, badge: finding.severity });
    }
    if (event.type === "evaluation.plan") {
      const eventFindings = Array.isArray(payload.findings) ? payload.findings : [];
      products.push({
        id: event.id,
        agent: "evaluation",
        title: "Evaluation plan",
        body: eventFindings.length > 0 ? `${eventFindings.length} benchmark improvement(s) ready. Open Insights for the full list.` : event.message,
      });
    }
    if (event.type === "node.update" || event.type === "edge.update") {
      products.push({ id: event.id, agent: "graph", title: "Research map update", body: event.message });
    }
  });
  return products;
}

function toActivity(event: AgentEvent) {
  if (event.payload?.local) return event;
  const message = humanizeEvent(event);
  if (!message) return null;
  return { ...event, message };
}

function humanizeEvent(event: AgentEvent) {
  const labels: Record<string, string> = {
    "session.created": "Session ready.",
    "paper.loading": "Reading paper.",
    "paper.parsed": "Paper parsed into sections and citations.",
    "paper.stored": "Original paper stored.",
    "paper.storage_failed": "Paper parsed locally.",
    "citation.resolving": "Checking citation context.",
    "citation.resolved": "Citation explanation added.",
    "critique.finding": "New insight added.",
    "experiment.missing": "Follow-up experiment identified.",
    "repo.ready": "Implementation repository found.",
    "code.generation_available": "Generated project option is ready.",
    "codegen.started": "Generating code project.",
    "codegen.progress": event.message,
    "codegen.done": "Generated code ZIP ready.",
    "math.issue": "Math issue added.",
    "replication.queued": "Replication plan ready.",
    "evaluation.plan": "Evaluation plan ready.",
    "benchmark.suggested": "Benchmark suggestion added.",
    "node.update": "Research map updated.",
    "edge.update": "Research map link added."
  };
  return labels[event.type] ?? (event.type === "agent.finished" ? event.message : "");
}

function formatTime(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default AgentPanel;
