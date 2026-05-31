import { Bot, ChevronDown, ChevronUp, FlaskConical, SearchCode } from "lucide-react";
import { useState } from "react";
import type { Citation, Paper, PaperSection } from "../types";

interface Props {
  paper: Paper | null;
  busy: boolean;
  onCitationClick: (citationId: string) => void;
  onRunAgent: (agentName: string, payload?: { section_id?: string }) => void;
}

function PaperViewer({ paper, busy, onCitationClick, onRunAgent }: Props) {
  if (!paper) {
    return (
      <div className="reader-empty">
        <h2>DeepPaper</h2>
        <p>Load a paper to start the agent graph.</p>
      </div>
    );
  }

  return (
    <div className="paper-viewer">
      <div className="paper-header">
        <div>
          <p className="eyebrow">Main Paper</p>
          <h2>{paper.title}</h2>
          <p className="paper-meta">
            {paper.authors.slice(0, 4).join(", ")}
            {paper.year ? ` | ${paper.year}` : ""}
          </p>
        </div>
        <div className="paper-actions">
          <button className="icon-button" disabled={busy} onClick={() => onRunAgent("critique")} title="Run Critique Agent">
            <Bot size={16} />
          </button>
          <button className="icon-button" disabled={busy} onClick={() => onRunAgent("code")} title="Run Code Agent">
            <SearchCode size={16} />
          </button>
          <button className="icon-button" disabled={busy} onClick={() => onRunAgent("replication")} title="Run Replication Agent">
            <FlaskConical size={16} />
          </button>
        </div>
      </div>
      {paper.sections.map((section) => (
        <SectionBlock
          key={section.id}
          section={section}
          citations={citationsForSection(paper.citations, section)}
          busy={busy}
          onCitationClick={onCitationClick}
          onRunAgent={onRunAgent}
        />
      ))}
    </div>
  );
}

function SectionBlock({ section, citations, busy, onCitationClick, onRunAgent }: {
  section: PaperSection;
  citations: Citation[];
  busy: boolean;
  onCitationClick: (citationId: string) => void;
  onRunAgent: (agentName: string, payload?: { section_id?: string }) => void;
}) {
  const [expanded, setExpanded] = useState(section.text.length < 1200);
  const text = expanded ? section.text : `${section.text.slice(0, 1200)}...`;

  return (
    <article className="section-block">
      <div className="section-heading">
        <h3>{section.title}</h3>
        <div className="section-actions">
          <button className="mini-button" disabled={busy} onClick={() => onRunAgent("critique", { section_id: section.id })}>
            <Bot size={14} />
            <span>Critique</span>
          </button>
          <button className="mini-button" disabled={busy} onClick={() => onRunAgent("evaluation", { section_id: section.id })}>
            <FlaskConical size={14} />
            <span>Evaluate</span>
          </button>
        </div>
      </div>
      <p className="section-text">{text}</p>
      {section.text.length > 1200 && (
        <button className="text-button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          <span>{expanded ? "Show less" : "Show more"}</span>
        </button>
      )}
      {citations.length > 0 && (
        <div className="citation-row">
          {citations.map((citation) => (
            <button key={citation.id} className="citation-chip" disabled={busy} onClick={() => onCitationClick(citation.id)}>
              <span>{citation.raw}</span>
              <strong>{citation.title ?? "Unresolved citation"}</strong>
            </button>
          ))}
        </div>
      )}
    </article>
  );
}

function citationsForSection(citations: Citation[], section: PaperSection) {
  const text = `${section.title} ${section.text}`;
  return citations.filter((citation) => text.includes(citation.raw) || (citation.context_snippet && text.includes(citation.context_snippet.slice(0, 30))));
}

export default PaperViewer;
