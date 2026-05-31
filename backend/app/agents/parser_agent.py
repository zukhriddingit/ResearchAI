from __future__ import annotations

import asyncio

from app.models import Claim, FigureExtract, Paper, PaperSection, new_id
from app.services.arxiv_client import fetch_arxiv_latex_source, fetch_arxiv_metadata, fetch_arxiv_pdf, normalize_arxiv_id
from app.services.llm import complete_with_vision
from app.services.pdf_parser import (
    attach_visuals_to_sections,
    enrich_citations_with_links,
    extract_citations,
    extract_equations_from_latex,
    extract_equations_from_text,
    extract_figures_from_pdf_bytes,
    extract_structured_document,
    extract_tables_from_pdf_bytes,
    extract_text_from_pdf_bytes,
    extract_title_from_text,
    split_into_sections,
)


PARSER_CLAIMS_PROMPT = "Extract concise scientific claims as JSON. Include section id, confidence, and evidence."
FIGURE_VISION_PROMPT = """You are a research paper figure analyst.
Describe this figure in 2-4 sentences for a researcher reading the paper.
Mention the visual type, axes or labels if visible, and the main result or comparison the figure communicates."""


async def run_parser_agent(session, source_type: str, source: str, event_emitter) -> Paper:
    event_emitter(session.session_id, "agent.started", "Parser Agent started.", agent="Parser", status="running")

    if source_type == "arxiv_url":
        arxiv_id = normalize_arxiv_id(source)
        if arxiv_id:
            metadata, pdf_bytes, latex_source = await asyncio.gather(
                fetch_arxiv_metadata(arxiv_id),
                fetch_arxiv_pdf(arxiv_id),
                fetch_arxiv_latex_source(arxiv_id),
                return_exceptions=True,
            )
            if isinstance(metadata, Exception):
                metadata = {}
            if isinstance(pdf_bytes, Exception):
                pdf_bytes = None
            if isinstance(latex_source, Exception):
                latex_source = ""
            title = metadata.get("title") or f"arXiv:{arxiv_id}"
            abstract = metadata.get("abstract") or "Metadata was fetched, but no abstract was available."
            authors = metadata.get("authors") or []
            year = metadata.get("year")
            sections: list[PaperSection]
            citations = []
            equations = []
            figures = []
            tables = []
            if pdf_bytes:
                full_text = extract_text_from_pdf_bytes(pdf_bytes)
                sections, equations = extract_structured_document(pdf_bytes)
                citations = extract_citations(full_text, sections) if full_text else []
                if citations and full_text:
                    references_index = full_text.lower().rfind("references")
                    enrich_citations_with_links(citations, full_text[references_index:] if references_index >= 0 else full_text[-4000:])
                latex_equations = extract_equations_from_latex(latex_source, sections) if latex_source else []
                if latex_equations:
                    equations = latex_equations
                figures = extract_figures_from_pdf_bytes(pdf_bytes, sections)
                tables = extract_tables_from_pdf_bytes(pdf_bytes, sections)
                if figures:
                    event_emitter(
                        session.session_id,
                        "paper.vision",
                        f"Describing {min(len(figures), 8)} figure(s) with the vision model.",
                        agent="Parser",
                        status="running",
                        payload={"figures": len(figures), "tables": len(tables)},
                    )
                    figures = await _describe_figures(figures)
                attach_visuals_to_sections(sections, figures=figures, tables=tables, equations=equations)
            else:
                sections = [
                    PaperSection(id="sec_abstract", title="Abstract", type="abstract", text=abstract),
                    PaperSection(
                        id="sec_next_steps",
                        title="Next Steps",
                        type="notes",
                        text="Upload the PDF for full-text parsing, citation extraction, and graph expansion.",
                    ),
                ]
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
                claims=_heuristic_claims(abstract or " ".join(section.text for section in sections[:2]), sections[0].id if sections else "sec_abstract"),
                equations=equations,
                is_main=True,
            )
            event_emitter(
                session.session_id,
                "agent.finished",
                f"Parser Agent loaded arXiv paper with {len(sections)} sections, {len(citations)} citations, {len(equations)} equations, {len(figures)} figures, and {len(tables)} tables.",
                agent="Parser",
                status="done",
            )
            return paper

    sections = split_into_sections(source)
    body = source.strip() or "No paper text provided."
    citations = extract_citations(body, sections)
    equations = extract_equations_from_text(body, sections)
    attach_visuals_to_sections(sections, equations=equations)
    title = extract_title_from_text(body) or "Untitled Uploaded Paper"
    paper = Paper(
        id=new_id("paper"),
        title=title,
        authors=[],
        abstract=sections[0].text[:500] if sections else body[:500],
        sections=sections or [PaperSection(id="sec_text", title="Paper Text", type="body", text=body)],
        citations=citations,
        claims=_heuristic_claims(body, sections[0].id if sections else "sec_text"),
        equations=equations,
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


async def _describe_figures(figures: list[FigureExtract], max_figures: int = 8) -> list[FigureExtract]:
    to_describe = [figure for figure in figures if figure.image_b64][:max_figures]
    remaining = figures[max_figures:]

    async def describe_one(figure: FigureExtract) -> FigureExtract:
        caption = f"Caption: {figure.caption}" if figure.caption else "No caption available."
        description = await complete_with_vision(
            FIGURE_VISION_PROMPT,
            f"{caption}\n\nDescribe what this research paper figure shows.",
            [figure.image_b64],
            fallback=figure.caption or "Figure from the paper.",
            temperature=0.1,
            max_tokens=500,
        )
        return figure.model_copy(update={"vision_description": description[:600]})

    if not to_describe:
        return figures
    described = await asyncio.gather(*(describe_one(figure) for figure in to_describe))
    return list(described) + remaining
