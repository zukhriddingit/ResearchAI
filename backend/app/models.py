from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Visual / equation extraction models
# ---------------------------------------------------------------------------

class FigureExtract(BaseModel):
    """A figure cropped from a PDF page, base64-encoded."""
    caption: str | None = None
    image_b64: str = ""
    page: int = 0
    section_id: str | None = None
    vision_description: str | None = None   # vision-LLM reading of the figure


class TableExtract(BaseModel):
    """A table extracted from a PDF page as structured rows."""
    caption: str | None = None
    rows: list[list[str]] = Field(default_factory=list)
    image_b64: str = ""
    section_id: str | None = None


class EquationExtract(BaseModel):
    """A mathematical equation extracted from the paper."""
    id: str = Field(default_factory=lambda: new_id("eq"))
    raw: str                      # text approximation (unicode chars, ASCII math)
    latex: str = ""               # LaTeX source when available (from arxiv source)
    label: str = ""               # equation number, e.g. "(1)" or "(2.3)"
    context_before: str = ""      # sentence(s) immediately preceding the equation
    context_after: str = ""       # sentence(s) immediately following
    section_id: str | None = None


# ---------------------------------------------------------------------------
# Agent trigger — structured handoff between agents
# ---------------------------------------------------------------------------

class AgentTrigger(BaseModel):
    target: str
    reason: str
    context: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core paper models
# ---------------------------------------------------------------------------

class PaperSection(BaseModel):
    id: str
    title: str
    type: str
    text: str
    level: int = 1                # heading depth: 1 = top-level, 2 = subsection, etc.
    start_offset: int | None = None
    end_offset: int | None = None
    figures: list[FigureExtract] = Field(default_factory=list)
    tables: list[TableExtract] = Field(default_factory=list)
    equations: list[EquationExtract] = Field(default_factory=list)


class Citation(BaseModel):
    id: str
    raw: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None        # e.g. "10.18653/v1/2022.acl-long.220"
    url: str | None = None        # best available URL (doi.org, arxiv, S2)
    semantic_scholar_id: str | None = None
    arxiv_id: str | None = None
    context_snippet: str | None = None
    resolved_paper_id: str | None = None


class Claim(BaseModel):
    id: str
    text: str
    section_id: str
    confidence: float = 0.5
    evidence: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    source_url: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    sections: list[PaperSection] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    equations: list[EquationExtract] = Field(default_factory=list)  # global equation list
    is_main: bool = False


# ---------------------------------------------------------------------------
# Code change models
# ---------------------------------------------------------------------------

class CodeEdit(BaseModel):
    """A concrete suggested code change produced by code/math/critique agents."""
    file_path: str
    change_type: Literal["add", "modify", "delete"] = "modify"
    description: str
    original_snippet: str = ""
    new_snippet: str = ""
    rationale: str = ""


class CodeChangeRequest(BaseModel):
    """A user-initiated or agent-triggered change request against the paper's code."""
    paper_id: str | None = None
    user_message: str = ""           # free-form user instruction
    finding_ids: list[str] = Field(default_factory=list)  # apply specific findings
    target_files: list[str] = Field(default_factory=list)


class CodeGenerateRequest(BaseModel):
    """Request to generate a full multi-file project from the paper."""
    paper_id: str | None = None
    include_tests: bool = True
    include_scripts: bool = True


# ---------------------------------------------------------------------------
# Graph models
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    status: str = "idle"
    paper_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)


class GraphState(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Session / event models
# ---------------------------------------------------------------------------

class AgentEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    session_id: str
    timestamp: str = Field(default_factory=utc_now)
    type: str
    agent: str | None = None
    status: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentFinding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("finding"))
    agent: str
    severity: Literal["low", "medium", "high"]
    title: str
    body: str
    related_paper_id: str | None = None
    related_section_id: str | None = None
    related_claim_id: str | None = None


class SessionState(BaseModel):
    session_id: str
    created_at: str = Field(default_factory=utc_now)
    main_paper_id: str | None = None
    papers: list[Paper] = Field(default_factory=list)
    graph: GraphState = Field(default_factory=GraphState)
    events: list[AgentEvent] = Field(default_factory=list)
    findings: list[AgentFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoadPaperRequest(BaseModel):
    source_type: Literal["arxiv_url", "pdf_text", "demo"]
    source: str


class AgentRunRequest(BaseModel):
    paper_id: str | None = None
    section_id: str | None = None
    citation_id: str | None = None
    mode: Literal["manual", "auto"] = "manual"


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str
    graph: GraphState
    events: list[AgentEvent]
