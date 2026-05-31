import { Activity, BookOpen, Brain, ChevronDown, FlaskConical, GitBranch, GitPullRequest, Radar, SearchCode, ShieldAlert } from "lucide-react";
import type { AgentEvent, AgentFinding } from "../types";
import FindingCard from "./FindingCard";

interface Props {
  events: AgentEvent[];
  findings: AgentFinding[];
  activeAgent: string | null;
  disabled: boolean;
  onRunAgent: (agentName: string) => void;
}

const assistantActions = [
  { agent: "reference", label: "Explain citations", icon: GitPullRequest, detail: "Connect the first citation to this paper" },
  { agent: "critique", label: "Review claims", icon: ShieldAlert, detail: "Surface weak baselines and missing checks" },
  { agent: "code", label: "Find implementation", icon: SearchCode, detail: "Look for code that matches the paper" },
  { agent: "replication", label: "Plan replication", icon: FlaskConical, detail: "Create a lightweight reproduction scorecard" },
  { agent: "evaluation", label: "Improve evaluation", icon: Activity, detail: "Suggest benchmarks and metrics" },
  { agent: "adversarial", label: "Stress test", icon: Radar, detail: "Challenge the strongest claims" },
  { agent: "graph", label: "Refresh map", icon: GitBranch, detail: "Sync the research map" }
];

function AgentPanel({ events, findings, activeAgent, disabled, onRunAgent }: Props) {
  const latest = [...events].reverse();
  const active = assistantActions.find((action) => action.agent === activeAgent);
  const recentActivity = latest.map(toActivity).filter((event): event is AgentEvent => event !== null).slice(0, 4);
  const products = buildWorkProducts(events);
  const technicalEvents = latest.slice(0, 14);

  return (
    <div className="panel agent-panel">
      <div className="panel-title">
        <Brain size={16} />
        <span>Research Assistants</span>
      </div>
      <div className={`agent-runner ${active ? "is-running" : ""}`}>
        <strong>{active ? active.label : latest[0] ? "Paper workspace ready" : "No paper loaded"}</strong>
        <span>{active ? active.detail : latest[0] ? humanizeEvent(latest[0]) : "Choose a demo, arXiv link, or upload."}</span>
      </div>
      <div className="agent-grid">
        {assistantActions.map(({ agent, label, icon: Icon, detail }) => {
          const isActive = activeAgent === agent;
          const status = isActive ? "running" : inferStatus(agent, latest);
          return (
            <button key={agent} className={`agent-card status-${status}`} disabled={disabled} onClick={() => onRunAgent(agent)}>
              <Icon size={16} />
              <span className="agent-name">{label}</span>
              <small>{statusLabel(status)}</small>
              <em>{detail}</em>
            </button>
          );
        })}
      </div>
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
                    Open source
                  </a>
                )}
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

function inferStatus(agent: string, latest: AgentEvent[]) {
  const aliases: Record<string, string[]> = {
    reference: ["reference"],
    critique: ["critique"],
    code: ["code"],
    replication: ["replication"],
    evaluation: ["evaluation"],
    adversarial: ["adversarial"],
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

function buildWorkProducts(events: AgentEvent[]) {
  const products: Array<{ id: string; title: string; body: string; href?: string }> = [];
  [...events].reverse().forEach((event) => {
    const payload = event.payload ?? {};
    if (event.type === "citation.resolved") {
      const summary = payload.summary as { relationship?: string; why_it_matters_for_main_paper?: string } | undefined;
      products.push({
        id: event.id,
        title: "Citation explained",
        body: summary?.why_it_matters_for_main_paper || summary?.relationship || event.message
      });
    }
    if (event.type === "repo.ready") {
      const repo = payload.repo as { full_name?: string; html_url?: string; match_reason?: string } | undefined;
      products.push({
        id: event.id,
        title: repo?.full_name || "Implementation found",
        body: repo?.match_reason || "A candidate implementation repository is ready.",
        href: repo?.html_url
      });
    }
    if (event.type === "replication.queued") {
      products.push({
        id: event.id,
        title: "Replication plan",
        body: String(payload.claim_under_test || payload.status || "A dry-run replication scorecard is ready.")
      });
    }
    if (event.type === "paper.stored") {
      products.push({
        id: event.id,
        title: "Upload saved",
        body: String(payload.public_id || "Original paper stored."),
        href: typeof payload.secure_url === "string" ? payload.secure_url : undefined
      });
    }
    if (event.type === "paper.storage_failed") {
      products.push({
        id: event.id,
        title: "Paper parsed locally",
        body: "Original-file storage was skipped, but the paper is ready to read."
      });
    }
    if (event.type === "benchmark.suggested") {
      products.push({ id: event.id, title: "Benchmark suggestion", body: event.message });
    }
    if (event.type === "attack.found") {
      products.push({ id: event.id, title: "Stress test", body: event.message });
    }
  });
  return products.slice(0, 4);
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
    "replication.queued": "Replication plan ready.",
    "benchmark.suggested": "Benchmark suggestion added.",
    "attack.found": "Stress test added.",
    "node.update": "Research map updated.",
    "edge.update": "Research map link added."
  };
  return labels[event.type] ?? (event.type === "agent.finished" ? event.message : "");
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    idle: "Ready",
    running: "Working",
    done: "Done",
    flagged: "Review",
    failed: "Failed",
    medium: "Review",
    high: "Review",
    low: "Done"
  };
  return labels[status] ?? status;
}

function formatTime(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default AgentPanel;
