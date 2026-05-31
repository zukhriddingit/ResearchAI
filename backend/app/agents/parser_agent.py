from __future__ import annotations

from app.models import Claim, Paper, PaperSection, new_id
from app.services.arxiv_client import fetch_arxiv_metadata, fetch_arxiv_pdf, normalize_arxiv_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json
from app.services.pdf_parser import (
    attach_visuals_to_sections,
    extract_citations,
    extract_figures_from_pdf_bytes,
    extract_tables_from_pdf_bytes,
    extract_text_from_pdf_bytes,
    split_into_sections,
)
from app.services.weave_tracing import op as weave_op


PARSER_CLAIMS_PROMPT = """\
You are a scientific claims extractor. Extract the 3-6 most important scientific claims from this research paper text.

Return JSON:
{
  "claims": [
    {"text": "...", "confidence": 0.0, "evidence": ["..."]}
  ]
}

Focus on: measurable performance claims, comparisons against baselines, proposed contributions, stated limitations.
Keep each claim text under 280 characters. Confidence 0.5-0.95 based on precision."""


@weave_op
async def run_parser_agent(session, source_type: str, source: str, event_emitter) -> Paper:
    """
    Parse a paper from demo fixture, arXiv URL, or raw text.
    For arXiv and PDF sources, also extracts figures and tables and attaches
    them to their owning sections for vision-augmented downstream agents.
    """
    event_emitter(session.session_id, "agent.started", "Parser Agent started.", agent="Parser", status="running")

    if source_type == "demo":
        paper = Paper.model_validate(load_lora_fixture()["main_paper"])
        event_emitter(session.session_id, "paper.parsed", "Parser Agent loaded the LoRA demo fixture.",
                      agent="Parser", status="done",
                      payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)})
        event_emitter(session.session_id, "agent.finished", "Parser Agent finished (demo).", agent="Parser", status="done")
        return paper

    if source_type == "arxiv_url":
        arxiv_id = normalize_arxiv_id(source)
        if arxiv_id:
            return await _parse_arxiv(session, source, arxiv_id, event_emitter)

    return await _parse_text(session, source, event_emitter)


@weave_op
async def _parse_arxiv(session, source: str, arxiv_id: str, event_emitter) -> Paper:
    metadata = await fetch_arxiv_metadata(arxiv_id)
    title = metadata.get("title") or f"arXiv:{arxiv_id}"
    abstract = metadata.get("abstract") or ""
    authors = metadata.get("authors") or []
    year = metadata.get("year")

    pdf_bytes = await fetch_arxiv_pdf(arxiv_id)
    text = extract_text_from_pdf_bytes(pdf_bytes) if pdf_bytes else ""

    sections = split_into_sections(text) if text else []
    citations = extract_citations(text, sections) if text else []

    # Extract figures and tables; attach them to their sections
    if pdf_bytes and sections:
        figures = extract_figures_from_pdf_bytes(pdf_bytes, sections)
        tables = extract_tables_from_pdf_bytes(pdf_bytes, sections)
        attach_visuals_to_sections(sections, figures, tables)
        fig_count = sum(len(s.figures) for s in sections)
        tab_count = sum(len(s.tables) for s in sections)
    else:
        fig_count = tab_count = 0

    if not sections:
        sections = [
            PaperSection(id="sec_abstract", title="Abstract", type="abstract",
                         text=abstract or f"Abstract for arXiv:{arxiv_id}"),
            PaperSection(id="sec_introduction", title="Introduction", type="introduction",
                         text="Full text available after PDF parsing is enabled."),
        ]

    claim_text = abstract or " ".join(s.text for s in sections[:2])
    claims = await _extract_claims(claim_text, sections[0].id)

    paper = Paper(
        id=f"paper_{arxiv_id.replace('.', '_')}",
        title=title, authors=authors, year=year, abstract=abstract,
        source_url=source, arxiv_id=arxiv_id,
        sections=sections, citations=citations, claims=claims, is_main=True,
    )
    event_emitter(session.session_id, "paper.parsed",
                  f"Parsed arXiv:{arxiv_id} — {len(sections)} sections, {len(citations)} citations, "
                  f"{fig_count} figures, {tab_count} tables.",
                  agent="Parser", status="done",
                  payload={"paper_id": paper.id, "sections": len(sections),
                           "citations": len(citations), "figures": fig_count, "tables": tab_count})
    event_emitter(session.session_id, "agent.finished", f"Parser Agent finished for {arxiv_id}.",
                  agent="Parser", status="done")
    return paper


@weave_op
async def _parse_text(session, source: str, event_emitter) -> Paper:
    body = source.strip() or "No paper text provided."
    sections = split_into_sections(body)
    citations = extract_citations(body, sections)
    claims = await _extract_claims(body, sections[0].id if sections else "sec_text")

    paper = Paper(
        id=new_id("paper"), title="Untitled Uploaded Paper", authors=[],
        abstract=sections[0].text[:500] if sections else body[:500],
        sections=sections or [PaperSection(id="sec_text", title="Paper Text", type="body", text=body)],
        citations=citations, claims=claims, is_main=True,
    )
    event_emitter(session.session_id, "paper.parsed",
                  f"Parsed uploaded text — {len(paper.sections)} sections, {len(paper.citations)} citations.",
                  agent="Parser", status="done",
                  payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)})
    event_emitter(session.session_id, "agent.finished", "Parser Agent finished (text upload).",
                  agent="Parser", status="done")
    return paper


@weave_op
async def _extract_claims(text: str, section_id: str) -> list[Claim]:
    if not text:
        return []
    heuristic = _heuristic_claims(text, section_id)
    result = await complete_json(PARSER_CLAIMS_PROMPT,
                                 f"Extract claims from this research paper text:\n\n{text[:4000]}",
                                 fallback={"claims": []})
    raw = result.get("claims", [])
    if not isinstance(raw, list) or not raw:
        return heuristic
    llm_claims: list[Claim] = []
    for c in raw[:6]:
        if not isinstance(c, dict) or not c.get("text"):
            continue
        llm_claims.append(Claim(
            id=new_id("claim"), text=str(c["text"])[:280], section_id=section_id,
            confidence=float(c.get("confidence", 0.65)),
            evidence=c["evidence"] if isinstance(c.get("evidence"), list) else ["LLM extraction"],
        ))
    return llm_claims or heuristic


def _heuristic_claims(text: str, section_id: str) -> list[Claim]:
    keywords = ["we propose", "we show", "we demonstrate", "outperforms", "reduces",
                "improves", "achieves", "efficient"]
    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    claims: list[Claim] = []
    for sentence in sentences:
        if len(sentence) > 30 and any(kw in sentence.lower() for kw in keywords):
            claims.append(Claim(id=new_id("claim"), text=sentence[:280], section_id=section_id,
                                confidence=0.55, evidence=["Heuristic claim extraction"]))
    return claims[:6]
