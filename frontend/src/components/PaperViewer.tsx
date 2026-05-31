import { Bot, ChevronDown, ChevronUp, ExternalLink, FileSearch, FlaskConical, SearchCode } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import type { Citation, EquationExtract, FigureExtract, Paper, PaperSection, TableExtract } from "../types";

interface Props {
  paper: Paper | null;
  busy: boolean;
  activeCitationId: string | null;
  onCitationClick: (citationId: string) => void;
  onRunAgent: (agentName: string, payload?: { section_id?: string }) => void;
  onAnalyzePaper: (paperId: string) => void;
}

function PaperViewer({ paper, busy, activeCitationId, onCitationClick, onRunAgent, onAnalyzePaper }: Props) {
  if (!paper) {
    return (
      <div className="reader-empty">
        <h2>DeepPaper</h2>
        <p>Open a paper to begin.</p>
      </div>
    );
  }

  const sections = paper.sections.length > 0
    ? paper.sections
    : paper.abstract
      ? [{ id: `${paper.id}_abstract`, title: "Abstract", type: "abstract", text: paper.abstract }]
      : [];
  const displaySections = orderSectionsForReading(sections);

  return (
    <div className="paper-viewer">
      <div className="paper-header">
        <div>
          <p className="eyebrow">{paper.is_main ? "Main Paper" : "Referenced Paper"}</p>
          <h2>{paper.title}</h2>
          <p className="paper-meta">
            {paper.authors.slice(0, 4).join(", ")}
            {paper.year ? ` | ${paper.year}` : ""}
          </p>
          {paper.source_url && (
            <a className="source-link" href={paper.source_url} target="_blank" rel="noreferrer">
              <ExternalLink size={13} />
              <span>Original paper</span>
            </a>
          )}
          {!paper.is_main && (
            <button className="analyze-paper-button" type="button" disabled={busy} onClick={() => onAnalyzePaper(paper.id)}>
              <FileSearch size={15} />
              <span>Analyze as new session</span>
            </button>
          )}
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
      {displaySections.length === 0 && (
        <div className="reader-empty compact">
          <h2>{paper.title}</h2>
          <p>No abstract or extracted text is available for this referenced paper yet.</p>
        </div>
      )}
      {displaySections.map((section) => (
        <SectionBlock
          key={section.id}
          section={section}
          citations={citationsForSection(paper.citations, section)}
          busy={busy}
          activeCitationId={activeCitationId}
          onCitationClick={onCitationClick}
          onRunAgent={onRunAgent}
        />
      ))}
    </div>
  );
}

function SectionBlock({ section, citations, busy, activeCitationId, onCitationClick, onRunAgent }: {
  section: PaperSection;
  citations: Citation[];
  busy: boolean;
  activeCitationId: string | null;
  onCitationClick: (citationId: string) => void;
  onRunAgent: (agentName: string, payload?: { section_id?: string }) => void;
}) {
  const [expanded, setExpanded] = useState(section.text.length < 1200);
  const [showAllCitations, setShowAllCitations] = useState(false);
  const text = expanded ? section.text : `${section.text.slice(0, 1200)}...`;
  const visibleCitations = showAllCitations ? citations : citations.slice(0, 18);
  const isReferenceSection = section.type === "references";

  return (
    <article className="section-block">
      <div className="section-heading">
        <h3>{section.title}</h3>
        {!isReferenceSection && (
          <div className="section-actions">
            <button className="mini-button" disabled={busy} onClick={() => onRunAgent("critique", { section_id: section.id })}>
              <Bot size={14} />
              <span>Critique this section</span>
            </button>
            <button className="mini-button" disabled={busy} onClick={() => onRunAgent("evaluation", { section_id: section.id })}>
              <FlaskConical size={14} />
              <span>Evaluate</span>
            </button>
            <button className="mini-button" disabled={busy} onClick={() => onRunAgent("code", { section_id: section.id })}>
              <SearchCode size={14} />
              <span>Find code</span>
            </button>
            <button className="mini-button" disabled={busy} onClick={() => onRunAgent("replication", { section_id: section.id })}>
              <FlaskConical size={14} />
              <span>Queue replication</span>
            </button>
          </div>
        )}
      </div>
      <div className="section-text">{renderTextWithCitations(text, citations, busy, activeCitationId, onCitationClick)}</div>
      <SectionVisuals section={section} />
      {section.text.length > 1200 && (
        <button className="text-button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          <span>{expanded ? "Show less" : "Show more"}</span>
        </button>
      )}
      {citations.length > 0 && (
        <div className="citation-row">
          {visibleCitations.map((citation) => (
            <button key={citation.id} className="citation-chip" disabled={busy} onClick={() => onCitationClick(citation.id)}>
              <span>{citation.raw}</span>
              <strong>{citationLabel(citation)}</strong>
            </button>
          ))}
          {citations.length > visibleCitations.length && (
            <button className="citation-chip citation-more" onClick={() => setShowAllCitations(true)}>
              <span>+{citations.length - visibleCitations.length}</span>
              <strong>Show more citations</strong>
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function SectionVisuals({ section }: { section: PaperSection }) {
  const figures = section.figures ?? [];
  const tables = section.tables ?? [];
  const equations = section.equations ?? [];
  if (figures.length === 0 && tables.length === 0 && equations.length === 0) return null;

  return (
    <div className="section-visuals">
      {figures.slice(0, 4).map((figure, index) => <FigureCard key={`${figure.page}-${index}`} figure={figure} />)}
      {tables.slice(0, 3).map((table, index) => <TableCard key={`${table.caption ?? "table"}-${index}`} table={table} />)}
      {equations.slice(0, 4).map((equation) => <EquationCard key={equation.id} equation={equation} />)}
    </div>
  );
}

function FigureCard({ figure }: { figure: FigureExtract }) {
  return (
    <figure className="paper-visual-card paper-figure-card">
      {figure.image_b64 && <img className="paper-figure" src={`data:image/png;base64,${figure.image_b64}`} alt={figure.caption ?? "Extracted research paper figure"} />}
      <figcaption>
        {figure.caption && <strong>{figure.caption}</strong>}
        {figure.vision_description && <span>{figure.vision_description}</span>}
      </figcaption>
    </figure>
  );
}

function TableCard({ table }: { table: TableExtract }) {
  const rows = table.rows ?? [];
  const previewRows = rows.slice(0, 8);
  const columnCount = Math.min(Math.max(...previewRows.map((row) => row.length), 0), 6);
  return (
    <div className="paper-visual-card paper-table-card">
      {table.caption && <strong>{table.caption}</strong>}
      {previewRows.length > 0 ? (
        <div className="table-scroll">
          <table>
            <tbody>
              {previewRows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.slice(0, columnCount).map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : table.image_b64 ? (
        <img className="paper-figure" src={`data:image/png;base64,${table.image_b64}`} alt={table.caption ?? "Extracted research paper table"} />
      ) : null}
    </div>
  );
}

function EquationCard({ equation }: { equation: EquationExtract }) {
  return (
    <div className="paper-visual-card paper-equation-card">
      <strong>{equation.label ? `Equation ${equation.label}` : "Equation"}</strong>
      <code>{equation.latex || equation.raw}</code>
    </div>
  );
}

function citationsForSection(citations: Citation[], section: PaperSection) {
  if (section.type === "references") return [];
  const text = `${section.title} ${section.text}`;
  return citations.filter((citation) => text.includes(citation.raw) || (citation.context_snippet && text.includes(citation.context_snippet.slice(0, 30))));
}

export default PaperViewer;

function orderSectionsForReading(sections: PaperSection[]) {
  return [...sections].sort((a, b) => {
    const aPriority = sectionReadPriority(a);
    const bPriority = sectionReadPriority(b);
    if (aPriority !== bPriority) return aPriority - bPriority;
    return (a.start_offset ?? 0) - (b.start_offset ?? 0);
  });
}

function sectionReadPriority(section: PaperSection) {
  if (section.type === "abstract") return 0;
  if (section.type === "references") return 2;
  return 1;
}

function citationLabel(citation: Citation) {
  if (citation.title) return citation.title;
  if (citation.authors.length > 0 && citation.year) return `${citation.authors[0]} et al., ${citation.year}`;
  return "Unresolved citation";
}

function renderTextWithCitations(
  text: string,
  citations: Citation[],
  busy: boolean,
  activeCitationId: string | null,
  onCitationClick: (citationId: string) => void
) {
  const matches = citations
    .flatMap((citation) => {
      const items: Array<{ start: number; end: number; citation: Citation }> = [];
      let cursor = text.indexOf(citation.raw);
      while (cursor >= 0) {
        items.push({ start: cursor, end: cursor + citation.raw.length, citation });
        cursor = text.indexOf(citation.raw, cursor + citation.raw.length);
      }
      return items;
    })
    .sort((a, b) => a.start - b.start);

  const nonOverlapping = matches.reduce<Array<{ start: number; end: number; citation: Citation }>>((acc, match) => {
    const previous = acc[acc.length - 1];
    if (!previous || match.start >= previous.end) acc.push(match);
    return acc;
  }, []);

  if (nonOverlapping.length === 0) return text;

  const chunks: ReactNode[] = [];
  let cursor = 0;
  nonOverlapping.forEach((match) => {
    if (match.start > cursor) {
      chunks.push(<span key={`text-${cursor}`}>{text.slice(cursor, match.start)}</span>);
    }
    chunks.push(
      <button
        key={`${match.citation.id}-${match.start}`}
        className={`inline-citation ${activeCitationId === match.citation.id ? "is-active" : ""}`}
        disabled={busy}
        title={match.citation.title ?? match.citation.raw}
        onClick={() => onCitationClick(match.citation.id)}
      >
        {match.citation.raw}
      </button>
    );
    cursor = match.end;
  });
  if (cursor < text.length) chunks.push(<span key={`text-${cursor}`}>{text.slice(cursor)}</span>);
  return chunks;
}
