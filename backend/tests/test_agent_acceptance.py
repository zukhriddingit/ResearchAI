"""
Acceptance tests for the DeepPaper ingestion/reference/critique pipeline.

Criteria:
1. Parser produces >= 4 sections and >= 4 citations from the LoRA demo fixture.
2. Reference Agent resolves demo Adapter citation with relationship + why_it_matters.
3. Critique Agent returns >= 2 findings for the Evaluation section.
4. No-API-key path works end-to-end (all keys absent).
5. External API failure path works (services degrade gracefully).
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# HTTP-layer acceptance tests (use FastAPI TestClient — no real HTTP calls)
# ---------------------------------------------------------------------------

def _make_client():
    from app.main import app
    return TestClient(app)


def test_parser_demo_produces_minimum_sections_and_citations():
    """Criterion 1: demo fixture must yield >= 4 sections and >= 4 citations."""
    client = _make_client()
    session_id = client.post("/api/sessions").json()["session_id"]
    loaded = client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    ).json()
    paper = loaded["paper"]
    assert paper["id"] == "paper_lora_main", "Expected the LoRA main paper fixture"
    assert len(paper["sections"]) >= 4, f"Expected >= 4 sections, got {len(paper['sections'])}"
    assert len(paper["citations"]) >= 4, f"Expected >= 4 citations, got {len(paper['citations'])}"


def test_reference_agent_resolves_adapter_citation():
    """Criterion 2: cit_adapter must resolve to paper_adapters with relationship + why_it_matters."""
    client = _make_client()
    session_id = client.post("/api/sessions").json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    )
    clicked = client.post(f"/api/sessions/{session_id}/citations/cit_adapter/click").json()
    assert clicked["referenced_paper"]["id"] == "paper_adapters"

    summary = clicked["summary"]
    assert summary.get("relationship"), "relationship must be non-empty"
    assert summary.get("why_it_matters_for_main_paper"), "why_it_matters_for_main_paper must be non-empty"
    # Summary must mention the main paper by name
    assert "LoRA" in summary["summary"], "summary must explicitly reference the main paper (LoRA)"


def test_critique_agent_returns_minimum_findings_for_evaluation_section():
    """Criterion 3: Critique Agent must return >= 2 findings when given the Evaluation section."""
    client = _make_client()
    session_id = client.post("/api/sessions").json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    )
    result = client.post(
        f"/api/sessions/{session_id}/agents/critique/run",
        json={"paper_id": "paper_lora_main", "section_id": "sec_evaluation", "mode": "manual"},
    ).json()
    findings = result["findings"]
    assert len(findings) >= 2, f"Expected >= 2 findings for Evaluation section, got {len(findings)}"
    # Each finding must have required fields
    for f in findings:
        assert f["agent"] == "Critique"
        assert f["severity"] in ("low", "medium", "high")
        assert f["title"]
        assert f["body"]


def test_critique_agent_full_paper_returns_findings():
    """Criterion 3 (variant): Critique on full paper without section filter also returns findings."""
    client = _make_client()
    session_id = client.post("/api/sessions").json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    )
    result = client.post(
        f"/api/sessions/{session_id}/agents/critique/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert result["findings"], "Expected at least one finding"


# ---------------------------------------------------------------------------
# No-API-key path (Criterion 4)
# ---------------------------------------------------------------------------

def test_no_api_key_path_works(monkeypatch):
    """Criterion 4: entire demo flow must succeed with no API keys in environment."""
    for var in ("ANTHROPIC_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "GITHUB_TOKEN", "WEAVE_PROJECT"):
        monkeypatch.delenv(var, raising=False)

    client = _make_client()
    session_id = client.post("/api/sessions").json()["session_id"]

    loaded = client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    ).json()
    assert len(loaded["paper"]["sections"]) >= 4

    clicked = client.post(f"/api/sessions/{session_id}/citations/cit_adapter/click").json()
    assert clicked["referenced_paper"]["id"] == "paper_adapters"

    critique = client.post(
        f"/api/sessions/{session_id}/agents/critique/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert critique["findings"]


# ---------------------------------------------------------------------------
# External API failure path (Criterion 5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_scholar_failure_degrades_gracefully():
    """Criterion 5: Semantic Scholar failure must not crash the Reference Agent."""
    from app.models import Citation, Paper
    from app.agents.reference_agent import run_reference_agent

    events = []

    def mock_emitter(session_id, event_type, message, **kwargs):
        events.append(event_type)
        from app.models import AgentEvent, new_id
        return AgentEvent(session_id=session_id, id=new_id("evt"), type=event_type, message=message)

    class FakeSession:
        session_id = "test-session"

    main_paper = Paper(
        id="paper_test",
        title="Test Paper About Neural Networks",
        abstract="We propose a method that outperforms baselines on NLP benchmarks.",
        is_main=True,
    )
    unknown_citation = Citation(
        id="cit_unknown_99",
        raw="[99]",
        title="Some Unknown Paper That Wont Be In Fixture",
        context_snippet="as shown in [99], this approach generalizes",
    )

    with patch("app.agents.reference_agent.search_paper", new_callable=AsyncMock, return_value=[]):
        result = await run_reference_agent(FakeSession(), main_paper, unknown_citation, mock_emitter)

    assert "referenced_paper" in result
    assert "summary" in result
    assert result["summary"]["relationship"]
    assert result["summary"]["why_it_matters_for_main_paper"]
    assert "agent.finished" in events


@pytest.mark.asyncio
async def test_arxiv_fetch_failure_produces_valid_paper():
    """Criterion 5: arXiv PDF fetch failure must produce a valid Paper (metadata-only)."""
    from app.agents.parser_agent import run_parser_agent

    events = []

    def mock_emitter(session_id, event_type, message, **kwargs):
        events.append(event_type)
        from app.models import AgentEvent, new_id
        return AgentEvent(session_id=session_id, id=new_id("evt"), type=event_type, message=message)

    class FakeSession:
        session_id = "test-session"

    with (
        patch("app.agents.parser_agent.fetch_arxiv_metadata", new_callable=AsyncMock) as mock_meta,
        patch("app.agents.parser_agent.fetch_arxiv_pdf", new_callable=AsyncMock, return_value=None),
    ):
        mock_meta.return_value = {
            "arxiv_id": "1234.56789",
            "title": "Attention Is All You Need",
            "abstract": "We propose a new network architecture, the Transformer.",
            "authors": ["Vaswani et al."],
            "year": 2017,
        }
        paper = await run_parser_agent(FakeSession(), "arxiv_url", "https://arxiv.org/abs/1234.56789", mock_emitter)

    assert paper.title == "Attention Is All You Need"
    assert paper.year == 2017
    assert paper.sections, "Must produce at least one section even without PDF"
    assert paper.claims, "Must produce at least one claim from abstract"
    assert "paper.parsed" in events


# ---------------------------------------------------------------------------
# Unit tests for services (no network)
# ---------------------------------------------------------------------------

def test_normalize_arxiv_id():
    from app.services.arxiv_client import normalize_arxiv_id

    assert normalize_arxiv_id("https://arxiv.org/abs/2106.09685") == "2106.09685"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2106.09685v2") == "2106.09685"
    assert normalize_arxiv_id("2106.09685") == "2106.09685"
    assert normalize_arxiv_id("not-an-id") is None


def test_split_into_sections_plain_headings():
    from app.services.pdf_parser import split_into_sections

    text = "Abstract\nThis is the abstract text.\nIntroduction\nThis is the intro.\nConclusion\nThis is the conclusion."
    sections = split_into_sections(text)
    titles = [s.title.lower() for s in sections]
    assert "abstract" in titles
    assert "introduction" in titles
    assert "conclusion" in titles


def test_split_into_sections_numbered_headings():
    from app.services.pdf_parser import split_into_sections

    text = "1 Introduction\nThis is the intro.\n2 Methodology\nThis is the method.\n3 Results\nThese are results."
    sections = split_into_sections(text)
    assert len(sections) >= 2, f"Expected >= 2 sections, got {len(sections)}: {[s.title for s in sections]}"


def test_extract_citations_numeric():
    from app.services.pdf_parser import extract_citations

    text = "Prior work [1] showed improvements. Recent studies [2,3] confirm this. See [4-6] for details."
    citations = extract_citations(text, [])
    ids = {c.id for c in citations}
    assert "cit_1" in ids
    assert "cit_2" in ids
    assert "cit_3" in ids


def test_extract_citations_author_year():
    from app.services.pdf_parser import extract_citations

    text = "As shown by Vaswani et al. (2017), attention mechanisms are powerful. Smith (2020) agrees."
    citations = extract_citations(text, [])
    assert len(citations) >= 1, "Should extract at least one author-year citation"
    years = [c.year for c in citations if c.year]
    assert 2017 in years


@pytest.mark.asyncio
async def test_llm_fallback_without_api_key(monkeypatch):
    """LLM wrapper must return fallback when ALL provider keys are absent."""
    # Clear every LLM credential so no provider can make a real call
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # Force a provider that has no key (groq with no key triggers fallback)
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    from app.services.llm import complete_json, complete_text

    fallback_dict = {"claims": [{"text": "fallback claim"}]}
    result = await complete_json("system", "user", fallback_dict)
    assert result == fallback_dict

    result_text = await complete_text("system", "user", "fallback text")
    assert result_text == "fallback text"


def test_fixture_reference_has_required_fields():
    """Fixture data must satisfy the Reference Agent's output contract."""
    from app.services.fixtures import load_lora_fixture

    fixture = load_lora_fixture()
    ref = fixture["references"]["cit_adapter"]
    assert ref["relationship"]
    assert ref["summary"]
    assert ref["why_it_matters_for_main_paper"]
    # Fixture summary must mention LoRA (the main paper)
    assert "LoRA" in ref["summary"] or "lora" in ref["summary"].lower()
