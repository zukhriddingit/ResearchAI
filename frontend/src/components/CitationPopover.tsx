import { Link2, Loader2 } from "lucide-react";
import type { CitationClickResponse } from "../types";

interface Props {
  result: CitationClickResponse | null;
  pendingCitation?: { id: string; label: string } | null;
}

function CitationPopover({ result, pendingCitation }: Props) {
  if (!result) {
    return (
      <aside className="citation-detail citation-detail-loading">
        <div className="panel-title">
          <Loader2 className="spin" size={16} />
          <span>Resolving citation</span>
        </div>
        <h3>{pendingCitation?.label ?? "Citation"}</h3>
        <p>Reference Agent is resolving this citation against the main paper context.</p>
        <div className="skeleton-stack" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </aside>
    );
  }

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
