from __future__ import annotations

import re

from app.models import Citation, GraphEdge, Paper, new_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json, reasoning_model
from app.services.semantic_scholar_client import search_paper


REFERENCE_CONTEXTUALIZATION_PROMPT = """You are the Reference Agent for DeepPaper.
Explain the cited paper only relative to the main paper.
Use one relationship from: extends, uses, contradicts, inspires, baseline_for, contextualizes, unknown.
The summary must explicitly mention the main paper title."""


async def run_reference_agent(session, main_paper: Paper, citation: Citation, event_emitter) -> dict:
    event_emitter(session.session_id, "agent.started", "Reference Agent started.", agent="Reference", status="running")
    fixture = load_lora_fixture()
    resolved = fixture["references"].get(citation.id)

    query = _citation_search_query(citation)
    if not resolved and query:
        matches = await search_paper(query, limit=1)
        if matches:
            match = matches[0]
            resolved = {
                "paper": {
                    "id": f"paper_{match.get('paperId', new_id('semantic'))}",
                    "title": match.get("title") or query,
                    "authors": [author.get("name", "") for author in match.get("authors", []) if author.get("name")],
                    "year": match.get("year"),
                    "abstract": match.get("abstract"),
                    "semantic_scholar_id": match.get("paperId"),
                    "sections": [],
                    "citations": [],
                    "claims": [],
                    "is_main": False,
                },
                "relationship": "unknown",
                "summary": f"Relative to {main_paper.title}, this reference appears relevant but needs deeper contextualization.",
                "why_it_matters_for_main_paper": "It was cited by the main paper and should be inspected before trusting the local claim.",
                "supporting_evidence": [citation.context_snippet or citation.raw],
                "possible_contradiction": None,
            }

    if not resolved and citation.title:
        title = _citation_search_query(citation)
        resolved = {
            "paper": {
                "id": f"paper_ref_{_slug(title)}",
                "title": title,
                "authors": citation.authors,
                "year": citation.year,
                "abstract": citation.context_snippet,
                "semantic_scholar_id": citation.semantic_scholar_id,
                "arxiv_id": citation.arxiv_id,
                "sections": [],
                "citations": [],
                "claims": [],
                "is_main": False,
            },
            "relationship": "contextualizes",
            "summary": f"Relative to {main_paper.title}, this cited work provides background for the local claim.",
            "why_it_matters_for_main_paper": "The paper cites it directly, so it should be part of the reading trail even when live metadata search is unavailable.",
            "supporting_evidence": [citation.context_snippet or citation.raw],
            "possible_contradiction": None,
        }

    if not resolved:
        resolved = fixture["references"]["cit_adapter"]

    paper = Paper.model_validate(resolved["paper"])
    fallback_summary = {
        "relationship": resolved.get("relationship", "unknown"),
        "summary": resolved.get("summary", ""),
        "why_it_matters_for_main_paper": resolved.get("why_it_matters_for_main_paper", ""),
        "supporting_evidence": resolved.get("supporting_evidence", []),
        "possible_contradiction": resolved.get("possible_contradiction"),
    }
    llm_summary = await complete_json(
        REFERENCE_CONTEXTUALIZATION_PROMPT,
        (
            f"Main paper: {main_paper.title}\n"
            f"Main abstract: {main_paper.abstract or ''}\n"
            f"Citation context: {citation.context_snippet or citation.raw}\n"
            f"Referenced paper: {paper.title}\n"
            f"Referenced abstract: {paper.abstract or ''}\n"
            "Return JSON with relationship, summary, why_it_matters_for_main_paper, "
            "supporting_evidence as a list, and possible_contradiction as string or null."
        ),
        fallback_summary,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=700,
    )
    relationship = str(llm_summary.get("relationship") or fallback_summary["relationship"])
    edge = GraphEdge(
        id=f"edge_{main_paper.id}_{paper.id}",
        source=f"node_{main_paper.id}",
        target=f"node_{paper.id}",
        type=relationship,
        label=relationship,
        confidence=0.78,
        evidence=_as_list(llm_summary.get("supporting_evidence")) or fallback_summary["supporting_evidence"],
    )
    summary = {
        "relationship": relationship,
        "summary": str(llm_summary.get("summary") or fallback_summary["summary"]),
        "why_it_matters_for_main_paper": str(
            llm_summary.get("why_it_matters_for_main_paper") or fallback_summary["why_it_matters_for_main_paper"]
        ),
        "supporting_evidence": _as_list(llm_summary.get("supporting_evidence")) or fallback_summary["supporting_evidence"],
        "possible_contradiction": llm_summary.get("possible_contradiction"),
        "edge": edge.model_dump(),
    }
    event_emitter(
        session.session_id,
        "agent.finished",
        "Reference Agent resolved a contextual citation.",
        agent="Reference",
        status="done",
        payload={"citation_id": citation.id, "paper_id": paper.id, "relationship": relationship},
    )
    return {"referenced_paper": paper, "summary": summary, "edge": edge}


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _citation_search_query(citation: Citation) -> str:
    if citation.title:
        return citation.title.split(";")[0].strip()
    return citation.raw.strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:80] or new_id("reference")
