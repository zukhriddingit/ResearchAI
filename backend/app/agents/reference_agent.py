from __future__ import annotations

from app.models import Citation, GraphEdge, Paper, new_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json
from app.services.semantic_scholar_client import search_paper
from app.services.weave_tracing import op as weave_op


REFERENCE_CONTEXTUALIZATION_PROMPT = """\
You are a research relationship analyst. Given a main paper and one of the papers it cites, produce a structured contextualization.

Rules:
- The "summary" MUST explicitly mention BOTH papers by name.
  Bad: "This paper introduces adapters."
  Good: "Relative to LoRA, this paper (Houlsby et al.) serves as the primary latency baseline — LoRA's claim of zero inference overhead is measured directly against adapter modules."
- "relationship" must be one of: extends | uses | contradicts | inspires | baseline_for | unknown
- "possible_contradiction" is a string describing a tension, or null if none.

Return only valid JSON with this exact schema:
{
  "relationship": "...",
  "summary": "...",
  "why_it_matters_for_main_paper": "...",
  "supporting_evidence": ["...", "..."],
  "possible_contradiction": "... or null"
}"""


@weave_op
async def run_reference_agent(session, main_paper: Paper, citation: Citation, event_emitter) -> dict:
    """
    Resolve a citation and produce a contextual summary relative to the main paper.

    Weave trace hierarchy:
        run_reference_agent
          ├── search_paper            (if not in fixture)
          └── _llm_contextualize
                └── complete_json
                      └── <LLM call — auto-traced>
    """
    event_emitter(session.session_id, "agent.started", "Reference Agent started.", agent="Reference", status="running")

    resolved = _try_fixture(citation)

    if not resolved:
        resolved = await _try_semantic_scholar(main_paper, citation)

    if not resolved:
        resolved = _fallback_resolved(main_paper, citation)

    paper = Paper.model_validate(resolved["paper"])
    relationship = resolved.get("relationship", "unknown")

    summary_text = _ensure_main_paper_named(resolved.get("summary", ""), main_paper.title, paper.title)
    why_matters = resolved.get("why_it_matters_for_main_paper") or (
        f"This reference contextualizes a specific claim made in {main_paper.title}."
    )

    edge = GraphEdge(
        id=f"edge_{main_paper.id}_{paper.id}",
        source=f"node_{main_paper.id}",
        target=f"node_{paper.id}",
        type=relationship,
        label=relationship,
        confidence=0.78,
        evidence=resolved.get("supporting_evidence", [citation.context_snippet or citation.raw]),
    )

    summary = {
        "relationship": relationship,
        "summary": summary_text,
        "why_it_matters_for_main_paper": why_matters,
        "supporting_evidence": resolved.get("supporting_evidence", []),
        "possible_contradiction": resolved.get("possible_contradiction"),
        "edge": edge.model_dump(),
    }

    if resolved.get("possible_contradiction"):
        event_emitter(
            session.session_id,
            "paper.contradiction",
            "Reference Agent found a potential contradiction or caveat.",
            agent="Reference",
            status="flagged",
            payload={"citation_id": citation.id, "note": resolved["possible_contradiction"]},
        )

    event_emitter(
        session.session_id,
        "agent.finished",
        f"Reference Agent resolved '{paper.title}' as {relationship}.",
        agent="Reference",
        status="done",
        payload={"citation_id": citation.id, "paper_id": paper.id, "relationship": relationship},
    )
    return {"referenced_paper": paper, "summary": summary, "edge": edge}


def _try_fixture(citation: Citation) -> dict | None:
    return load_lora_fixture()["references"].get(citation.id)


@weave_op
async def _try_semantic_scholar(main_paper: Paper, citation: Citation) -> dict | None:
    """Search Semantic Scholar and LLM-contextualize the best match."""
    if not citation.title:
        return None
    matches = await search_paper(citation.title, limit=1)
    if not matches:
        return None
    match = matches[0]
    ref_paper_dict = {
        "id": f"paper_{match.get('paperId', new_id('semantic'))}",
        "title": match.get("title") or citation.title,
        "authors": [a.get("name", "") for a in match.get("authors", []) if a.get("name")],
        "year": match.get("year"),
        "abstract": match.get("abstract"),
        "semantic_scholar_id": match.get("paperId"),
        "sections": [],
        "citations": [],
        "claims": [],
        "is_main": False,
    }
    context = await _llm_contextualize(main_paper, ref_paper_dict, citation)
    return {"paper": ref_paper_dict, **context}


def _fallback_resolved(main_paper: Paper, citation: Citation) -> dict:
    ref_title = citation.title or citation.raw
    return {
        "paper": {
            "id": f"paper_{new_id('cit')}",
            "title": ref_title,
            "authors": citation.authors or [],
            "year": citation.year,
            "abstract": None,
            "sections": [],
            "citations": [],
            "claims": [],
            "is_main": False,
        },
        "relationship": "unknown",
        "summary": (
            f"Relative to {main_paper.title}, this reference ({ref_title}) "
            f"appears in context: {citation.context_snippet or citation.raw}"
        ),
        "why_it_matters_for_main_paper": (
            f"It was cited by {main_paper.title}. Reviewing it will "
            "clarify whether the local claim depends critically on this work."
        ),
        "supporting_evidence": [citation.context_snippet or citation.raw],
        "possible_contradiction": None,
    }


@weave_op
async def _llm_contextualize(main_paper: Paper, ref_paper_dict: dict, citation: Citation) -> dict:
    """Call LLM to generate structured citation contextualization. Falls back gracefully."""
    ref_title = ref_paper_dict.get("title") or citation.title or "Unknown"
    ref_abstract = ref_paper_dict.get("abstract") or ""
    user_msg = (
        f"Main paper: {main_paper.title}\n"
        f"Main paper abstract: {(main_paper.abstract or '')[:800]}\n\n"
        f"Reference paper: {ref_title}\n"
        f"Reference abstract: {ref_abstract[:600]}\n"
        f"Citation context snippet: {citation.context_snippet or citation.raw}"
    )
    fallback = {
        "relationship": "unknown",
        "summary": (
            f"Relative to {main_paper.title}, this reference ({ref_title}) "
            f"is cited in context: {citation.context_snippet or citation.raw}"
        ),
        "why_it_matters_for_main_paper": (
            f"It was cited by {main_paper.title} and should be inspected "
            "relative to the local claim."
        ),
        "supporting_evidence": [citation.context_snippet or citation.raw],
        "possible_contradiction": None,
    }
    return await complete_json(REFERENCE_CONTEXTUALIZATION_PROMPT, user_msg, fallback)


def _ensure_main_paper_named(summary: str, main_title: str, ref_title: str) -> str:
    if main_title and main_title.split()[0] not in summary:
        prefix = f"Relative to {main_title}, "
        summary = prefix + summary[0].lower() + summary[1:] if summary else prefix + ref_title
    return summary
