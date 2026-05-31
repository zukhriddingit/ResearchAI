import type { AgentFinding } from "../types";

interface Props {
  finding: AgentFinding;
}

function FindingCard({ finding }: Props) {
  return (
    <div className={`finding-card severity-${finding.severity}`}>
      <span>{finding.severity}</span>
      <strong>{finding.title}</strong>
      <p>{finding.body}</p>
    </div>
  );
}

export default FindingCard;

