export interface PaperSection {
  id: string;
  title: string;
  type: string;
  text: string;
  start_offset?: number | null;
  end_offset?: number | null;
}

export interface Citation {
  id: string;
  raw: string;
  title?: string | null;
  authors: string[];
  year?: number | null;
  semantic_scholar_id?: string | null;
  arxiv_id?: string | null;
  context_snippet?: string | null;
  resolved_paper_id?: string | null;
}

export interface Claim {
  id: string;
  text: string;
  section_id: string;
  confidence: number;
  evidence: string[];
}

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year?: number | null;
  abstract?: string | null;
  source_url?: string | null;
  arxiv_id?: string | null;
  semantic_scholar_id?: string | null;
  sections: PaperSection[];
  citations: Citation[];
  claims: Claim[];
  is_main: boolean;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  status: string;
  paper_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  confidence?: number | null;
  evidence: string[];
}

export interface GraphState {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AgentEvent {
  id: string;
  session_id: string;
  timestamp: string;
  type: string;
  agent?: string | null;
  status?: string | null;
  message: string;
  payload: Record<string, unknown>;
}

export interface AgentFinding {
  id: string;
  agent: string;
  severity: "low" | "medium" | "high";
  title: string;
  body: string;
  related_paper_id?: string | null;
  related_section_id?: string | null;
  related_claim_id?: string | null;
}

export interface SessionState {
  session_id: string;
  created_at: string;
  main_paper_id?: string | null;
  papers: Paper[];
  graph: GraphState;
  events: AgentEvent[];
  findings: AgentFinding[];
}

export interface CitationClickResponse {
  citation: Citation;
  referenced_paper: Paper;
  summary: {
    relationship: string;
    summary: string;
    why_it_matters_for_main_paper: string;
    supporting_evidence: string[];
    possible_contradiction?: string | null;
  };
  graph: GraphState;
  events: AgentEvent[];
  findings: AgentFinding[];
}

export interface AgentRunRequest {
  paper_id?: string;
  section_id?: string;
  citation_id?: string;
  mode?: "manual" | "auto";
}

