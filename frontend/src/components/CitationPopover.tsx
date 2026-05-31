import { Link2 } from "lucide-react";
import type { CitationClickResponse } from "../types";

interface Props {
  result: CitationClickResponse;
}

function CitationPopover({ result }: Props) {
  return (
    <aside className="citation-detail">
      <div className="panel-title">
        <Link2 size={16} />
        <span>{result.summary.relationship}</span>
      </div>
      <h3>{result.referenced_paper.title}</h3>
      <p>{result.summary.summary}</p>
      <div className="callout">
        <strong>Why it matters</strong>
        <span>{result.summary.why_it_matters_for_main_paper}</span>
      </div>
      {result.summary.possible_contradiction && (
        <div className="callout warn">
          <strong>Caveat</strong>
          <span>{result.summary.possible_contradiction}</span>
        </div>
      )}
    </aside>
  );
}

export default CitationPopover;

