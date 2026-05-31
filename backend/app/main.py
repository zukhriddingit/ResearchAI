from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from app.agents.adversarial_agent import run_adversarial_agent
from app.agents.code_agent import run_code_agent
from app.agents.critique_agent import run_critique_agent
from app.agents.evaluation_agent import run_evaluation_agent
from app.agents.parser_agent import run_parser_agent
from app.agents.reference_agent import run_reference_agent
from app.agents.replication_agent import run_replication_agent
from app.events import emit, stream_events
from app.models import (
    AgentRunRequest,
    CreateSessionResponse,
    GraphEdge,
    GraphNode,
    LoadPaperRequest,
    Paper,
)
from app.services.cloudinary_storage import upload_paper_asset
from app.services.pdf_parser import extract_text_from_pdf_bytes
from app.services.weave_tracing import log_event, trace_agent_run, traced_agent_call
from app.store import store


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(title="DeepPaper API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "deeppaper-backend"}


@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    session = store.create_session()
    event = emit(session.session_id, "session.created", "DeepPaper session created.", agent="Graph", status="done")
    log_event(event)
    return CreateSessionResponse(
        session_id=session.session_id,
        created_at=session.created_at,
        graph=session.graph,
        events=session.events,
    )


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    return _session_or_404(session_id)


@app.get("/api/sessions/{session_id}/events")
def get_events(session_id: str):
    return _session_or_404(session_id).events


@app.get("/api/sessions/{session_id}/events/stream")
def events_stream(session_id: str):
    _session_or_404(session_id)
    return StreamingResponse(stream_events(session_id), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/papers/load")
async def load_paper(session_id: str, request: LoadPaperRequest):
    session = _session_or_404(session_id)
    emit(session_id, "paper.loading", "Loading paper source.", agent="Parser", status="running", payload=request.model_dump())
    paper = await traced_agent_call(
        "Parser",
        request.model_dump(),
        lambda: run_parser_agent(session, request.source_type, request.source, emit),
    )
    store.add_paper(session_id, paper)

    node = GraphNode(
        id=f"node_{paper.id}",
        label=paper.title,
        type="paper",
        status="main" if paper.is_main else "referenced",
        paper_id=paper.id,
        metadata={"authors": paper.authors, "year": paper.year, "arxiv_id": paper.arxiv_id},
    )
    store.add_node(session_id, node)
    emit(
        session_id,
        "paper.parsed",
        "Main paper parsed into sections, citations, and claims.",
        agent="Parser",
        status="done",
        payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)},
    )
    emit(session_id, "node.update", "Main paper node added to graph.", agent="Graph", status="done", payload=node.model_dump())
    trace_agent_run("Parser", request.model_dump(), {"paper_id": paper.id})

    session = store.get_session(session_id)
    return {"paper": paper, "graph": session.graph, "events": session.events}


@app.post("/api/sessions/{session_id}/papers/upload")
async def upload_paper(session_id: str, file: UploadFile = File(...)):
    session = _session_or_404(session_id)
    filename = file.filename or "uploaded-paper"
    content_type = file.content_type or "application/octet-stream"
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(file_bytes) > 35 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Uploaded file is larger than the 35 MB demo limit")

    emit(
        session_id,
        "paper.loading",
        f"Uploading and parsing {filename}.",
        agent="Parser",
        status="running",
        payload={"filename": filename, "content_type": content_type, "bytes": len(file_bytes)},
    )

    paper_text = _extract_uploaded_text(file_bytes, filename, content_type)
    if len(paper_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Could not extract enough text from the uploaded paper")

    cloudinary_asset = await upload_paper_asset(file_bytes, filename, content_type)
    if cloudinary_asset and cloudinary_asset.get("secure_url"):
        emit(
            session_id,
            "paper.stored",
            "Original uploaded paper stored in Cloudinary.",
            agent="Storage",
            status="done",
            payload=cloudinary_asset,
        )
    elif cloudinary_asset and cloudinary_asset.get("error"):
        emit(
            session_id,
            "paper.storage_failed",
            "Cloudinary storage failed, but local parsing will continue.",
            agent="Storage",
            status="failed",
            payload={"error": cloudinary_asset.get("error"), "folder": cloudinary_asset.get("folder")},
        )

    paper = await traced_agent_call(
        "Parser",
        {"source_type": "upload", "filename": filename, "content_type": content_type, "bytes": len(file_bytes)},
        lambda: run_parser_agent(session, "pdf_text", paper_text, emit),
    )
    if not paper.title.strip() or paper.title == "Untitled Uploaded Paper":
        paper.title = _title_from_filename(filename)
    if cloudinary_asset and cloudinary_asset.get("secure_url"):
        paper.source_url = str(cloudinary_asset["secure_url"])
    store.add_paper(session_id, paper)

    node_metadata = {
        "authors": paper.authors,
        "year": paper.year,
        "filename": filename,
        "content_type": content_type,
        "stored_in_cloudinary": bool(cloudinary_asset and cloudinary_asset.get("secure_url")),
    }
    if cloudinary_asset and cloudinary_asset.get("secure_url"):
        node_metadata.update(
            {
                "cloudinary_public_id": cloudinary_asset.get("public_id"),
                "cloudinary_url": cloudinary_asset.get("secure_url"),
                "cloudinary_folder": cloudinary_asset.get("folder"),
            }
        )
    node = GraphNode(
        id=f"node_{paper.id}",
        label=paper.title,
        type="paper",
        status="main",
        paper_id=paper.id,
        metadata=node_metadata,
    )
    store.add_node(session_id, node)
    emit(
        session_id,
        "paper.parsed",
        "Uploaded paper parsed into sections, citations, and claims.",
        agent="Parser",
        status="done",
        payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)},
    )
    emit(session_id, "node.update", "Uploaded paper node added to graph.", agent="Graph", status="done", payload=node.model_dump())
    trace_agent_run("UploadParser", {"filename": filename, "content_type": content_type}, {"paper_id": paper.id, "stored": bool(cloudinary_asset)})

    session = store.get_session(session_id)
    return {"paper": paper, "graph": session.graph, "events": session.events, "cloudinary_asset": cloudinary_asset}


@app.post("/api/sessions/{session_id}/citations/{citation_id}/click")
async def click_citation(session_id: str, citation_id: str):
    session = _session_or_404(session_id)
    main_paper = _main_paper_or_404(session)
    citation = _citation_or_404(main_paper, citation_id)

    emit(session_id, "citation.clicked", f"Citation {citation.raw} clicked.", agent="Reader", status="done", payload={"citation_id": citation.id})
    emit(session_id, "citation.resolving", "Reference Agent resolving citation in main-paper context.", agent="Reference", status="running")
    reference_result = await traced_agent_call(
        "Reference",
        {"session_id": session_id, "main_paper_id": main_paper.id, "citation_id": citation.id},
        lambda: run_reference_agent(session, main_paper, citation, emit),
    )
    referenced_paper: Paper = reference_result["referenced_paper"]
    citation.resolved_paper_id = referenced_paper.id
    store.add_paper(session_id, main_paper)
    store.add_paper(session_id, referenced_paper)

    ref_node = GraphNode(
        id=f"node_{referenced_paper.id}",
        label=referenced_paper.title,
        type="paper",
        status="referenced",
        paper_id=referenced_paper.id,
        metadata={"authors": referenced_paper.authors, "year": referenced_paper.year},
    )
    edge: GraphEdge = reference_result["edge"]
    store.add_node(session_id, ref_node)
    store.add_edge(session_id, edge)
    emit(
        session_id,
        "citation.resolved",
        "Citation resolved relative to the main paper.",
        agent="Reference",
        status="done",
        payload={"citation": citation.model_dump(), "summary": reference_result["summary"]},
    )
    emit(session_id, "node.update", "Reference paper node added to graph.", agent="Graph", status="done", payload=ref_node.model_dump())
    emit(session_id, "edge.update", "Contextual citation edge added to graph.", agent="Graph", status="done", payload=edge.model_dump())

    if reference_result["summary"].get("possible_contradiction"):
        emit(
            session_id,
            "paper.contradiction",
            "Reference Agent found a caveat worth checking.",
            agent="Reference",
            status="flagged",
            payload={"citation_id": citation.id, "note": reference_result["summary"]["possible_contradiction"]},
        )

    critique_section = main_paper.sections[1] if len(main_paper.sections) > 1 else None
    findings = await traced_agent_call(
        "Critique",
        {"session_id": session_id, "paper_id": main_paper.id, "section_id": critique_section.id if critique_section else None},
        lambda: run_critique_agent(session, main_paper, critique_section, main_paper, emit),
    )
    for finding in findings:
        store.add_finding(session_id, finding)

    code_result = await traced_agent_call(
        "Code",
        {"session_id": session_id, "paper_id": main_paper.id, "finding_id": findings[0].id if findings else None},
        lambda: run_code_agent(session, main_paper, finding=findings[0] if findings else None, event_emitter=emit),
    )
    _add_repo_to_graph(session_id, main_paper, code_result["repo"])
    replication_result = await traced_agent_call(
        "Replication",
        {"session_id": session_id, "paper_id": main_paper.id, "repo": code_result["repo"].get("full_name")},
        lambda: run_replication_agent(session, main_paper, repo=code_result["repo"], finding=findings[0] if findings else None, event_emitter=emit),
    )
    trace_agent_run("ReferenceClick", {"citation_id": citation_id}, {"paper_id": referenced_paper.id, "repo": code_result["repo"]["full_name"]})

    session = store.get_session(session_id)
    return {
        "citation": citation,
        "referenced_paper": referenced_paper,
        "summary": reference_result["summary"],
        "code": code_result,
        "replication": replication_result,
        "graph": session.graph,
        "events": session.events,
        "findings": session.findings,
    }


@app.post("/api/sessions/{session_id}/agents/{agent_name}/run")
async def run_agent(session_id: str, agent_name: str, request: AgentRunRequest):
    session = _session_or_404(session_id)
    paper = _paper_by_id(session, request.paper_id) if request.paper_id else _main_paper_or_404(session)
    section = _section_by_id(paper, request.section_id) if request.section_id else None
    started_at = len(session.events)
    findings = []
    output: Any

    try:
        normalized_agent = agent_name.lower()
        if normalized_agent == "parser":
            output = {"message": "Parser is run through /papers/load in this starter."}
            emit(session_id, "agent.finished", "Parser endpoint hint returned.", agent="Parser", status="done", payload=output)
        elif normalized_agent == "reference":
            citation = _citation_or_404(paper, request.citation_id or (paper.citations[0].id if paper.citations else ""))
            output = await traced_agent_call(
                "Reference",
                {"session_id": session_id, "paper_id": paper.id, "citation_id": citation.id},
                lambda: run_reference_agent(session, paper, citation, emit),
            )
        elif normalized_agent == "critique":
            findings = await traced_agent_call(
                "Critique",
                {"session_id": session_id, "paper_id": paper.id, "section_id": section.id if section else None},
                lambda: run_critique_agent(session, paper, section, paper, emit),
            )
            for finding in findings:
                store.add_finding(session_id, finding)
            output = {"findings": [finding.model_dump() for finding in findings]}
        elif normalized_agent == "code":
            output = await traced_agent_call(
                "Code",
                {"session_id": session_id, "paper_id": paper.id, "section_id": section.id if section else None},
                lambda: run_code_agent(session, paper, section=section, event_emitter=emit),
            )
            _add_repo_to_graph(session_id, paper, output["repo"])
        elif normalized_agent == "replication":
            output = await traced_agent_call(
                "Replication",
                {"session_id": session_id, "paper_id": paper.id},
                lambda: run_replication_agent(session, paper, event_emitter=emit),
            )
        elif normalized_agent == "evaluation":
            findings = await traced_agent_call(
                "Evaluation",
                {"session_id": session_id, "paper_id": paper.id, "section_id": section.id if section else None},
                lambda: run_evaluation_agent(session, paper, section=section, event_emitter=emit),
            )
            for finding in findings:
                store.add_finding(session_id, finding)
            output = {"findings": [finding.model_dump() for finding in findings]}
        elif normalized_agent == "adversarial":
            output = await traced_agent_call(
                "Adversarial",
                {"session_id": session_id, "paper_id": paper.id},
                lambda: run_adversarial_agent(session, paper, event_emitter=emit),
            )
        else:
            output = {"message": f"{agent_name} is not implemented yet. Deterministic stub completed."}
            emit(session_id, "agent.started", f"{agent_name} stub started.", agent=agent_name, status="running")
            emit(session_id, "agent.finished", f"{agent_name} stub finished.", agent=agent_name, status="done", payload=output)
    except Exception as exc:
        emit(session_id, "agent.failed", f"{agent_name} failed: {exc}", agent=agent_name, status="failed")
        raise

    trace_agent_run(agent_name, request.model_dump(), output if isinstance(output, dict) else {"output": str(output)})
    session = store.get_session(session_id)
    return {
        "agent": agent_name,
        "output": _serializable(output),
        "events": session.events[started_at:],
        "findings": session.findings,
        "graph": session.graph,
    }


def _session_or_404(session_id: str):
    try:
        return store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


def _main_paper_or_404(session) -> Paper:
    if session.main_paper_id:
        for paper in session.papers:
            if paper.id == session.main_paper_id:
                return paper
    raise HTTPException(status_code=404, detail="Main paper not loaded")


def _paper_by_id(session, paper_id: str | None) -> Paper:
    for paper in session.papers:
        if paper.id == paper_id:
            return paper
    raise HTTPException(status_code=404, detail="Paper not found")


def _citation_or_404(paper: Paper, citation_id: str) -> Any:
    for citation in paper.citations:
        if citation.id == citation_id:
            return citation
    raise HTTPException(status_code=404, detail="Citation not found")


def _section_by_id(paper: Paper, section_id: str | None):
    for section in paper.sections:
        if section.id == section_id:
            return section
    raise HTTPException(status_code=404, detail="Section not found")


def _extract_uploaded_text(file_bytes: bytes, filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if content_type == "application/pdf" or suffix == ".pdf":
        return extract_text_from_pdf_bytes(file_bytes)
    if content_type.startswith("text/") or suffix in {".txt", ".md", ".markdown", ".tex"}:
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="ignore")
    raise HTTPException(status_code=400, detail="Only PDF and plain text uploads are supported in this demo")


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip() or "Uploaded Paper"
    return " ".join(stem.replace("_", " ").replace("-", " ").split()).title()


def _add_repo_to_graph(session_id: str, paper: Paper, repo: dict[str, Any]) -> None:
    safe_name = (repo.get("full_name") or repo.get("name") or "repo").replace("/", "_").replace(" ", "_").lower()
    node = GraphNode(
        id=f"node_repo_{safe_name}",
        label=repo.get("full_name") or repo.get("name") or "Implementation repo",
        type="code",
        status="code-found",
        metadata=repo,
    )
    edge = GraphEdge(
        id=f"edge_{paper.id}_{node.id}",
        source=f"node_{paper.id}",
        target=node.id,
        type="implements",
        label="implements",
        confidence=0.72,
        evidence=[repo.get("match_reason", "Code Agent selected this repo.")],
    )
    store.add_node(session_id, node)
    store.add_edge(session_id, edge)
    emit(session_id, "node.update", "Code repo node added to graph.", agent="Graph", status="done", payload=node.model_dump())
    emit(session_id, "edge.update", "Implementation edge added to graph.", agent="Graph", status="done", payload=edge.model_dump())


def _serializable(output: Any) -> Any:
    if hasattr(output, "model_dump"):
        return output.model_dump()
    if isinstance(output, dict):
        return {key: _serializable(value) for key, value in output.items()}
    if isinstance(output, list):
        return [_serializable(item) for item in output]
    return output
