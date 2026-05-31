from __future__ import annotations

import asyncio

from app.models import Claim, EquationExtract, FigureExtract, Paper, PaperSection, new_id
from app.services.arxiv_client import (
    fetch_arxiv_latex_source,
    fetch_arxiv_metadata,
    fetch_arxiv_pdf,
    normalize_arxiv_id,
)
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json, complete_text, complete_with_vision
from app.services.pdf_parser import (
    attach_visuals_to_sections,
    enrich_citations_with_links,
    extract_citations,
    extract_equations_from_latex,
    extract_figures_from_pdf_bytes,
    extract_structured_document,
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

FIGURE_VISION_PROMPT = """\
You are a research paper figure analyst. Describe this figure from a research paper in 2-4 sentences.

Cover:
- What type of figure it is (plot, diagram, table, architecture, flowchart, etc.)
- What the axes / labels show (if a graph)
- The key result or insight the figure communicates
- Any notable trend, comparison, or anomaly visible

Be specific. Refer to actual values, labels, or curve names you can read."""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@weave_op
async def run_parser_agent(session, source_type: str, source: str, event_emitter) -> Paper:
    event_emitter(session.session_id, "agent.started", "Parser Agent started.",
                  agent="Parser", status="running")

    if source_type == "demo":
        paper = Paper.model_validate(load_lora_fixture()["main_paper"])
        event_emitter(session.session_id, "paper.parsed",
                      "Parser Agent loaded the LoRA demo fixture.",
                      agent="Parser", status="done",
                      payload={"paper_id": paper.id, "sections": len(paper.sections),
                               "citations": len(paper.citations)})
        event_emitter(session.session_id, "agent.finished",
                      "Parser Agent finished (demo).", agent="Parser", status="done")
        return paper

    if source_type == "arxiv_url":
        arxiv_id = normalize_arxiv_id(source)
        if arxiv_id:
            return await _parse_arxiv(session, source, arxiv_id, event_emitter)

    return await _parse_text(session, source, event_emitter)


# ---------------------------------------------------------------------------
# arXiv path — full structured extraction
# ---------------------------------------------------------------------------

@weave_op
async def _parse_arxiv(session, source: str, arxiv_id: str, event_emitter) -> Paper:
    event_emitter(session.session_id, "paper.fetching",
                  f"Fetching arXiv:{arxiv_id} metadata and PDF …",
                  agent="Parser", status="running")

    # Fetch in parallel: metadata, PDF, LaTeX source
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

    title    = metadata.get("title") or f"arXiv:{arxiv_id}"
    abstract = metadata.get("abstract") or ""
    authors  = metadata.get("authors") or []
    year     = metadata.get("year")

    # ── Structural section + equation extraction ──────────────────────────
    sections: list[PaperSection] = []
    equations: list[EquationExtract] = []

    if pdf_bytes:
        event_emitter(session.session_id, "paper.parsing",
                      "Extracting structured sections and equations from PDF …",
                      agent="Parser", status="running")
        sections, pdf_equations = extract_structured_document(pdf_bytes)
        equations.extend(pdf_equations)

    # LaTeX source gives cleaner equations; merge / prefer LaTeX ones
    if latex_source and sections:
        event_emitter(session.session_id, "paper.equations",
                      "Extracting equations from LaTeX source …",
                      agent="Parser", status="running")
        latex_equations = extract_equations_from_latex(latex_source, sections)
        if latex_equations:
            # Use LaTeX equations as primary (they have proper .latex field)
            equations = latex_equations

    # ── Citations ─────────────────────────────────────────────────────────
    raw_text = ""
    if pdf_bytes:
        raw_text = extract_text_from_pdf_bytes(pdf_bytes)
    citations = extract_citations(raw_text, sections) if raw_text else []
    if citations and raw_text:
        # Extract bib section text for link enrichment
        bib_start = raw_text.lower().rfind("references")
        bib_text = raw_text[bib_start:] if bib_start >= 0 else raw_text[-4000:]
        enrich_citations_with_links(citations, bib_text)

    # ── Figures & tables ──────────────────────────────────────────────────
    figures = extract_figures_from_pdf_bytes(pdf_bytes, sections) if pdf_bytes else []
    tables  = extract_tables_from_pdf_bytes(pdf_bytes, sections)  if pdf_bytes else []

    # ── Vision-describe figures (concurrently, up to 8) ───────────────────
    if figures:
        event_emitter(session.session_id, "paper.vision",
                      f"Vision-describing {min(len(figures), 8)} figures …",
                      agent="Parser", status="running")
        figures = await _describe_figures(figures)

    attach_visuals_to_sections(sections, figures, tables, equations)

    # ── Fallback sections if PDF parse failed ─────────────────────────────
    if not sections:
        sections = [
            PaperSection(id="sec_abstract", title="Abstract", type="abstract",
                         text=abstract or f"Abstract for arXiv:{arxiv_id}"),
            PaperSection(id="sec_introduction", title="Introduction", type="introduction",
                         text="Full text available after PDF parsing."),
        ]

    # ── Claims ────────────────────────────────────────────────────────────
    claim_text = abstract or " ".join(s.text for s in sections[:2])
    claims = await _extract_claims(claim_text, sections[0].id)

    fig_count = sum(len(s.figures) for s in sections)
    tab_count = sum(len(s.tables) for s in sections)
    eq_count  = sum(len(s.equations) for s in sections)

    paper = Paper(
        id=f"paper_{arxiv_id.replace('.', '_')}",
        title=title, authors=authors, year=year, abstract=abstract,
        source_url=source, arxiv_id=arxiv_id,
        sections=sections, citations=citations, claims=claims,
        equations=equations, is_main=True,
    )

    event_emitter(session.session_id, "paper.parsed",
                  f"Parsed arXiv:{arxiv_id} — {len(sections)} sections, "
                  f"{len(citations)} citations, {eq_count} equations, "
                  f"{fig_count} figures, {tab_count} tables.",
                  agent="Parser", status="done",
                  payload={"paper_id": paper.id, "sections": len(sections),
                           "citations": len(citations), "equations": eq_count,
                           "figures": fig_count, "tables": tab_count})
    event_emitter(session.session_id, "agent.finished",
                  f"Parser Agent finished for {arxiv_id}.", agent="Parser", status="done")
    return paper


# ---------------------------------------------------------------------------
# Plain text path
# ---------------------------------------------------------------------------

@weave_op
async def _parse_text(session, source: str, event_emitter) -> Paper:
    body = source.strip() or "No paper text provided."
    sections = split_into_sections(body)
    citations = extract_citations(body, sections)
    claims = await _extract_claims(body, sections[0].id if sections else "sec_text")

    paper = Paper(
        id=new_id("paper"), title="Untitled Uploaded Paper", authors=[],
        abstract=sections[0].text[:500] if sections else body[:500],
        sections=sections or [PaperSection(id="sec_text", title="Paper Text",
                                           type="body", text=body)],
        citations=citations, claims=claims, is_main=True,
    )
    event_emitter(session.session_id, "paper.parsed",
                  f"Parsed uploaded text — {len(paper.sections)} sections, "
                  f"{len(paper.citations)} citations.",
                  agent="Parser", status="done",
                  payload={"paper_id": paper.id, "sections": len(paper.sections),
                           "citations": len(paper.citations)})
    event_emitter(session.session_id, "agent.finished",
                  "Parser Agent finished (text upload).", agent="Parser", status="done")
    return paper


# ---------------------------------------------------------------------------
# Vision description of figures
# ---------------------------------------------------------------------------

@weave_op
async def _describe_figures(figures: list[FigureExtract], max_figures: int = 8) -> list[FigureExtract]:
    """
    Run each figure image through the vision LLM to get a natural-language description.
    Processes up to max_figures concurrently; returns updated list with .vision_description set.
    """
    to_describe = [f for f in figures if f.image_b64][:max_figures]
    unchanged   = figures[max_figures:]

    async def _describe_one(fig: FigureExtract) -> FigureExtract:
        caption_ctx = f"Caption: {fig.caption}" if fig.caption else "No caption available."
        user_msg = f"{caption_ctx}\n\nDescribe what you see in this research paper figure."
        description = await complete_with_vision(
            FIGURE_VISION_PROMPT,
            user_msg,
            [fig.image_b64],
            fallback=fig.caption or "Figure from paper.",
        )
        return fig.model_copy(update={"vision_description": description[:600]})

    described = await asyncio.gather(*[_describe_one(f) for f in to_describe])
    # figures beyond cap keep vision_description=None
    return list(described) + unchanged


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

@weave_op
async def _extract_claims(text: str, section_id: str) -> list[Claim]:
    if not text:
        return []
    heuristic = _heuristic_claims(text, section_id)
    result = await complete_json(
        PARSER_CLAIMS_PROMPT,
        f"Extract claims from this research paper text:\n\n{text[:4000]}",
        fallback={"claims": []},
    )
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
            claims.append(Claim(
                id=new_id("claim"), text=sentence[:280], section_id=section_id,
                confidence=0.55, evidence=["Heuristic claim extraction"],
            ))
    return claims[:6]
