import { Activity, Bot, FlaskConical, GitPullRequest, Radar, SearchCode, ShieldAlert } from "lucide-react";
import type { AgentEvent, AgentFinding } from "../types";

interface Props {
  events: AgentEvent[];
  findings: AgentFinding[];
  disabled: boolean;
  onRunAgent: (agentName: string) => void;
}

const agents = [
  { name: "Parser", icon: Bot },
  { name: "Reference", icon: GitPullRequest },
  { name: "Critique", icon: ShieldAlert },
  { name: "Code", icon: SearchCode },
  { name: "Replication", icon: FlaskConical },
  { name: "Evaluation", icon: Activity },
  { name: "Adversarial", icon: Radar }
];

function AgentPanel({ events, findings, disabled, onRunAgent }: Props) {
  const latest = [...events].reverse();

  return (
    <div className="panel agent-panel">
      <div className="panel-title">
        <Activity size={16} />
        <span>Agents</span>
      </div>
      <div className="agent-grid">
        {agents.map(({ name, icon: Icon }) => {
          const status = inferStatus(name, latest);
          return (
            <button key={name} className={`agent-card status-${status}`} disabled={disabled} onClick={() => onRunAgent(name.toLowerCase())}>
              <Icon size={16} />
              <span>{name}</span>
              <small>{status}</small>
            </button>
          );
        })}
      </div>
      <div className="feed-section">
        <h3>Event Feed</h3>
        <div className="event-feed">
          {latest.slice(0, 18).map((event) => (
            <div className="event-row" key={event.id}>
              <div>
                <span className="event-type">{event.type}</span>
                <p>{event.message}</p>
              </div>
              <small>{event.agent ?? "System"}</small>
            </div>
          ))}
          {latest.length === 0 && <div className="empty-feed">Waiting for session events.</div>}
        </div>
      </div>
      <div className="feed-section">
        <h3>Findings</h3>
        <div className="finding-list">
          {findings.slice(-5).reverse().map((finding) => (
            <div key={finding.id} className={`finding-card severity-${finding.severity}`}>
              <span>{finding.severity}</span>
              <strong>{finding.title}</strong>
              <p>{finding.body}</p>
            </div>
          ))}
          {findings.length === 0 && <div className="empty-feed">No findings yet.</div>}
        </div>
      </div>
    </div>
  );
}

function inferStatus(agent: string, latest: AgentEvent[]) {
  const event = latest.find((item) => item.agent?.toLowerCase() === agent.toLowerCase());
  if (!event) return "idle";
  if (event.status === "running") return "running";
  if (event.status === "failed") return "failed";
  if (event.status === "flagged" || event.type.includes("finding") || event.type.includes("missing") || event.type.includes("attack")) return "flagged";
  if (event.status === "done" || event.type === "agent.finished") return "done";
  return event.status ?? "done";
}

export default AgentPanel;

