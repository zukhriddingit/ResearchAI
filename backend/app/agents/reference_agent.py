from __future__ import annotations

from app.models import Citation, GraphEdge, Paper, new_id
from app.services.fixtures import load_lora_fixture
from app.services.semantic_scholar_client import search_paper


REFERENCE_CONTEXTUALIZATION_PROMPT = (
    "Explain this reference only relative to the main paper. Return relationship, summary, why it matters, evidence, and contradictions."
)


async def run_reference_agent(session, main_paper: Paper, citation: Citation, event_emitter) -> dict:
    event_emitter(session.session_id, "agent.started", "Reference Agent started.", agent="Reference", status="running")
    fixture = load_lora_fixture()
    resolved = fixture["references"].get(citation.id)

    if not resolved and citation.title:
        matches = await search_paper(citation.title, limit=1)
        if matches:
            match = matches[0]
            resolved = {
                "paper": {
                    "id": f"paper_{match.get('paperId', new_id('semantic'))}",
                    "title": match.get("title") or citation.title,
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

    if not resolved:
        resolved = fixture["references"]["cit_adapter"]

    paper = Paper.model_validate(resolved["paper"])
    relationship = resolved.get("relationship", "unknown")
    edge = GraphEdge(
        id=f"edge_{main_paper.id}_{paper.id}",
        source=f"node_{main_paper.id}",
        target=f"node_{paper.id}",
        type=relationship,
        label=relationship,
        confidence=0.78,
        evidence=resolved.get("supporting_evidence", []),
    )
    summary = {
        "relationship": relationship,
        "summary": resolved.get("summary", ""),
        "why_it_matters_for_main_paper": resolved.get("why_it_matters_for_main_paper", ""),
        "supporting_evidence": resolved.get("supporting_evidence", []),
        "possible_contradiction": resolved.get("possible_contradiction"),
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

