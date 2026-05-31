from __future__ import annotations

from app.models import Claim, Paper, PaperSection, new_id
from app.services.arxiv_client import fetch_arxiv_metadata, normalize_arxiv_id
from app.services.fixtures import load_lora_fixture
from app.services.pdf_parser import extract_citations, extract_title_from_text, split_into_sections


PARSER_CLAIMS_PROMPT = "Extract concise scientific claims as JSON. Include section id, confidence, and evidence."


async def run_parser_agent(session, source_type: str, source: str, event_emitter) -> Paper:
    event_emitter(session.session_id, "agent.started", "Parser Agent started.", agent="Parser", status="running")

    if source_type == "demo":
        paper = Paper.model_validate(load_lora_fixture()["main_paper"])
        event_emitter(
            session.session_id,
            "agent.finished",
            "Parser Agent loaded the LoRA fixture.",
            agent="Parser",
            status="done",
            payload={"paper_id": paper.id, "sections": len(paper.sections), "citations": len(paper.citations)},
        )
        return paper

    if source_type == "arxiv_url":
        arxiv_id = normalize_arxiv_id(source)
        if arxiv_id:
            metadata = await fetch_arxiv_metadata(arxiv_id)
            title = metadata.get("title") or f"arXiv:{arxiv_id}"
            abstract = metadata.get("abstract") or "Metadata was fetched, but no abstract was available."
            paper = Paper(
                id=f"paper_{arxiv_id.replace('.', '_')}",
                title=title,
                authors=[],
                year=None,
                abstract=abstract,
                source_url=source,
                arxiv_id=arxiv_id,
                sections=[
                    PaperSection(id="sec_abstract", title="Abstract", type="abstract", text=abstract),
                    PaperSection(
                        id="sec_next_steps",
                        title="Next Steps",
                        type="notes",
                        text="PDF parsing can be enabled by Team 2. The fixture path is ready for the demo.",
                    ),
                ],
                citations=[],
                claims=_heuristic_claims(abstract, "sec_abstract"),
                is_main=True,
            )
            event_emitter(session.session_id, "agent.finished", "Parser Agent fetched arXiv metadata.", agent="Parser", status="done")
            return paper

    sections = split_into_sections(source)
    body = source.strip() or "No paper text provided."
    citations = extract_citations(body, sections)
    title = extract_title_from_text(body) or "Untitled Uploaded Paper"
    paper = Paper(
        id=new_id("paper"),
        title=title,
        authors=[],
        abstract=sections[0].text[:500] if sections else body[:500],
        sections=sections or [PaperSection(id="sec_text", title="Paper Text", type="body", text=body)],
        citations=citations,
        claims=_heuristic_claims(body, sections[0].id if sections else "sec_text"),
        is_main=True,
    )
    event_emitter(session.session_id, "agent.finished", "Parser Agent parsed supplied text.", agent="Parser", status="done")
    return paper


def _heuristic_claims(text: str, section_id: str) -> list[Claim]:
    claim_words = ["we propose", "we show", "outperforms", "reduces", "improves", "efficient", "achieves"]
    sentences = [part.strip() for part in text.replace("\n", " ").split(".") if part.strip()]
    claims: list[Claim] = []
    for sentence in sentences:
        if any(word in sentence.lower() for word in claim_words):
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
