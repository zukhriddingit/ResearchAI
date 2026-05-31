from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class PaperSection(BaseModel):
    id: str
    title: str
    type: str
    text: str
    start_offset: int | None = None
    end_offset: int | None = None


class Citation(BaseModel):
    id: str
    raw: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
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
    is_main: bool = False


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

