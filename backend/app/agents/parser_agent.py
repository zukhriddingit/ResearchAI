from __future__ import annotations

from app.models import Claim, Paper, PaperSection, new_id
from app.services.arxiv_client import fetch_arxiv_metadata, fetch_arxiv_pdf, normalize_arxiv_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json
from app.services.pdf_parser import extract_citations, extract_text_from_pdf_bytes, split_into_sections
from app.services.weave_tracing import op as weave_op


PARSER_CLAIMS_PROMPT = """\
You are a scientific claims extractor. Given text from a research paper, extract the 3-6 most important scientific claims.

Return JSON with this exact schema:
{
  "claims": [
    {
      "text": "...",
      "confidence": 0.0,
      "evidence": ["..."]
    }
  ]
}

Focus on: measurable performance claims, comparisons against baselines, proposed contributions, and stated limitations.
Keep each claim text under 280 characters. Confidence 0.5-0.95 based on how precisely the claim is stated."""


@weave_op
async def run_parser_agent(session, source_type: str, source: str, event_emitter) -> Paper:
    """
    Parse a paper from one of three source types: demo, arxiv_url, or pdf_text.

    Weave trace hierarchy:
        run_parser_agent
          ├── fetch_arxiv_metadata   (if arxiv_url)
          ├── fetch_arxiv_pdf        (if arxiv_url)
          └── _extract_claims
                └── complete_json
                      └── <LLM call — auto-traced>
    """
    event_emitter(session.session_id, "agent.started", "Parser Agent started.", agent="Parser", status="running")

    if source_type == "demo":
        paper = Paper.model_validate(load_lora_fixture()["main_paper"])
        event_emitter(
            session.session_id,
            "paper.parsed",
            "Parser Agent loaded the LoRA demo fixture.",
            agent="Parser",
            status="done",
            payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)},
        )
        event_emitter(session.session_id, "agent.finished", "Parser Agent finished (demo).", agent="Parser", status="done")
        return paper

    if source_type == "arxiv_url":
        arxiv_id = normalize_arxiv_id(source)
        if arxiv_id:
            return await _parse_arxiv(session, source, arxiv_id, event_emitter)

    return await _parse_text(session, source, event_emitter)


@weave_op
async def _parse_arxiv(session, source: str, arxiv_id: str, event_emitter) -> Paper:
    """Fetch arXiv metadata, attempt PDF parse, fall back to metadata-only sections."""
    metadata = await fetch_arxiv_metadata(arxiv_id)
    title = metadata.get("title") or f"arXiv:{arxiv_id}"
    abstract = metadata.get("abstract") or ""
    authors = metadata.get("authors") or []
    year = metadata.get("year")

    text = ""
    pdf_bytes = await fetch_arxiv_pdf(arxiv_id)
    if pdf_bytes:
        text = extract_text_from_pdf_bytes(pdf_bytes)

    sections = split_into_sections(text) if text else []
    citations = extract_citations(text, sections) if text else []

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
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        source_url=source,
        arxiv_id=arxiv_id,
        sections=sections,
        citations=citations,
        claims=claims,
        is_main=True,
    )
    event_emitter(
        session.session_id,
        "paper.parsed",
        f"Parser Agent parsed arXiv:{arxiv_id} ({len(sections)} sections, {len(citations)} citations).",
        agent="Parser",
        status="done",
        payload={"paper_id": paper.id, "sections": len(sections), "citations": len(citations)},
    )
    event_emitter(session.session_id, "agent.finished", f"Parser Agent finished for {arxiv_id}.", agent="Parser", status="done")
    return paper


@weave_op
async def _parse_text(session, source: str, event_emitter) -> Paper:
    """Parse raw uploaded paper text."""
    body = source.strip() or "No paper text provided."
    sections = split_into_sections(body)
    citations = extract_citations(body, sections)
    claims = await _extract_claims(body, sections[0].id if sections else "sec_text")

    paper = Paper(
        id=new_id("paper"),
        title="Untitled Uploaded Paper",
        authors=[],
        abstract=sections[0].text[:500] if sections else body[:500],
        sections=sections or [PaperSection(id="sec_text", title="Paper Text", type="body", text=body)],
        citations=citations,
        claims=claims,
        is_main=True,
    )
    event_emitter(
        session.session_id,
        "paper.parsed",
        f"Parser Agent parsed uploaded text ({len(paper.sections)} sections, {len(paper.citations)} citations).",
        agent="Parser",
        status="done",
        payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)},
    )
    event_emitter(session.session_id, "agent.finished", "Parser Agent finished (text upload).", agent="Parser", status="done")
    return paper


@weave_op
async def _extract_claims(text: str, section_id: str) -> list[Claim]:
    """Extract claims via LLM if key present; otherwise heuristic keyword scan."""
    if not text:
        return []

    heuristic = _heuristic_claims(text, section_id)
    result = await complete_json(
        PARSER_CLAIMS_PROMPT,
        f"Extract claims from this research paper text:\n\n{text[:4000]}",
        fallback={"claims": []},
    )
    raw_claims = result.get("claims", [])
    if not isinstance(raw_claims, list) or not raw_claims:
        return heuristic

    llm_claims: list[Claim] = []
    for c in raw_claims[:6]:
        if not isinstance(c, dict) or not c.get("text"):
            continue
        llm_claims.append(
            Claim(
                id=new_id("claim"),
                text=str(c["text"])[:280],
                section_id=section_id,
                confidence=float(c.get("confidence", 0.65)),
                evidence=(c["evidence"] if isinstance(c.get("evidence"), list) else ["LLM extraction"]),
            )
        )
    return llm_claims or heuristic


def _heuristic_claims(text: str, section_id: str) -> list[Claim]:
    keywords = ["we propose", "we show", "we demonstrate", "outperforms", "reduces", "improves", "achieves", "efficient"]
    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    claims: list[Claim] = []
    for sentence in sentences:
        if len(sentence) > 30 and any(kw in sentence.lower() for kw in keywords):
            claims.append(
                Claim(
                    id=new_id("claim"),
                    text=sentence[:280],
                    section_id=section_id,
                    confidence=0.55,
                    evidence=["Heuristic claim extraction"],
                )
            )
    return claims[:6]
