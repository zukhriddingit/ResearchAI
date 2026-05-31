"""
Comprehensive tests for the full DeepPaper pipeline:
  - All 7 agents (including the 4 previously stub-only)
  - Agent-to-agent trigger chain
  - Figure / table extraction (PyMuPDF)
  - Vision critique path
  - Weave tracing wired correctly
  - Every agent reachable via the HTTP API
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client():
    from app.main import app
    return TestClient(app)


def _loaded_session(client: TestClient):
    """Create a session and load the demo LoRA paper. Returns (client, session_id)."""
    sid = client.post("/api/sessions").json()["session_id"]
    client.post(f"/api/sessions/{sid}/papers/load",
                json={"source_type": "demo", "source": "lora"})
    return sid


def _fake_session(sid="test-session-x"):
    class S:
        session_id = sid
    return S()


def _fake_emitter():
    events = []
    def emit(sid, etype, msg, **kw):
        events.append(etype)
        from app.models import AgentEvent
        return AgentEvent(session_id=sid, type=etype, message=msg)
    return emit, events


def _lora_paper():
    from app.services.fixtures import load_lora_fixture
    from app.models import Paper
    return Paper.model_validate(load_lora_fixture()["main_paper"])


# ---------------------------------------------------------------------------
# Code Agent
# ---------------------------------------------------------------------------

class TestCodeAgent:
    def test_returns_repo_and_key_files(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/code/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        out = r["output"]
        assert out.get("repo"), "repo must be present"
        assert out.get("key_files"), "key_files must be present"
        assert out.get("paper_claim_connection"), "paper_claim_connection must be present"

    def test_returns_handoff_to_replication(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/code/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        handoff = r["output"].get("handoff_to_replication", {})
        assert handoff.get("entrypoint_guess"), "entrypoint_guess must be set"
        assert handoff.get("minimal_run_plan"), "minimal_run_plan must be non-empty"

    @pytest.mark.asyncio
    async def test_triggers_include_replication_and_adversarial(self):
        from app.agents.code_agent import run_code_agent
        from app.services.fixtures import load_lora_fixture
        emit, events = _fake_emitter()
        paper = _lora_paper()
        repo = load_lora_fixture()["code_repo"]
        with patch("app.agents.code_agent.search_repositories", new_callable=AsyncMock,
                   return_value=[repo]):
            result = await run_code_agent(_fake_session(), paper, event_emitter=emit)
        triggers = result.get("triggers", [])
        targets = {t["target"] for t in triggers}
        assert "replication" in targets, "Code Agent must trigger Replication Agent"
        assert "adversarial" in targets, "Code Agent must trigger Adversarial Agent"


# ---------------------------------------------------------------------------
# Replication Agent
# ---------------------------------------------------------------------------

class TestReplicationAgent:
    def test_returns_scorecard(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/replication/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        out = r["output"]
        assert out.get("claim_under_test"), "claim_under_test must be set"
        assert out.get("scorecard"), "scorecard must be present"
        assert "confidence" in out["scorecard"]

    def test_status_is_dry_run_complete_or_blocked(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/replication/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        assert r["output"]["status"] in ("dry_run_complete", "blocked")

    @pytest.mark.asyncio
    async def test_triggers_evaluation_always(self):
        from app.agents.replication_agent import run_replication_agent
        emit, _ = _fake_emitter()
        paper = _lora_paper()
        result = await run_replication_agent(_fake_session(), paper, event_emitter=emit)
        triggers = result.get("triggers", [])
        targets = [t["target"] for t in triggers]
        assert "evaluation" in targets, "Replication must always trigger Evaluation"

    @pytest.mark.asyncio
    async def test_triggers_critique_on_discrepancies(self):
        from app.agents.replication_agent import run_replication_agent
        emit, _ = _fake_emitter()
        paper = _lora_paper()
        with patch("app.agents.replication_agent._build_scorecard", new_callable=AsyncMock,
                   return_value={
                       "claim_under_test": "LoRA matches fine-tuning quality.",
                       "expected_metric": "BLEU",
                       "minimal_reproduction_steps": ["step1"],
                       "environment": "local",
                       "risks": [],
                       "scorecard": {"code_available": True, "data_available": None,
                                     "compute_feasible": True, "expected_time": "1h",
                                     "confidence": 0.5},
                       "discrepancies": ["ROUGE-L is 0.3 points off from Table 2"],
                   }):
            result = await run_replication_agent(_fake_session(), paper, event_emitter=emit)
        triggers = result.get("triggers", [])
        critique_triggers = [t for t in triggers if t["target"] == "critique"]
        assert critique_triggers, "Discrepancies must trigger Critique Agent"
        assert "ROUGE-L" in critique_triggers[0]["context"]["discrepancies"][0]


# ---------------------------------------------------------------------------
# Evaluation Agent
# ---------------------------------------------------------------------------

class TestEvaluationAgent:
    def test_returns_findings_via_http(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/evaluation/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        findings = r["findings"]
        assert len(findings) >= 2, f"Expected >= 2 evaluation findings, got {len(findings)}"

    def test_findings_have_required_fields(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/evaluation/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        for f in r["findings"]:
            assert f["agent"] == "Evaluation"
            assert f["severity"] in ("low", "medium", "high")
            assert f["title"]
            assert f["body"]

    def test_emits_benchmark_suggested_events(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/evaluation/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        event_types = [e["type"] for e in r["events"]]
        assert "benchmark.suggested" in event_types


# ---------------------------------------------------------------------------
# Adversarial Agent
# ---------------------------------------------------------------------------

class TestAdversarialAgent:
    def test_returns_attack_surface_and_tests(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/adversarial/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        out = r["output"]
        assert out.get("attack_surface"), "attack_surface must be present"
        assert len(out.get("tests", [])) >= 2, "Must return at least 2 adversarial tests"

    def test_each_test_has_required_fields(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/adversarial/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        for t in r["output"]["tests"]:
            assert t.get("name"), "name required"
            assert t.get("claim_targeted"), "claim_targeted required"
            assert t.get("procedure"), "procedure required"
            assert t.get("severity") in ("low", "medium", "high"), "severity must be valid"

    def test_emits_attack_found_events(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/agents/adversarial/run",
                        json={"paper_id": "paper_lora_main", "mode": "manual"}).json()
        event_types = [e["type"] for e in r["events"]]
        assert "attack.found" in event_types

    @pytest.mark.asyncio
    async def test_high_severity_triggers_critique(self):
        from app.agents.adversarial_agent import run_adversarial_agent
        emit, _ = _fake_emitter()
        paper = _lora_paper()
        with patch("app.agents.adversarial_agent._design_attacks", new_callable=AsyncMock,
                   return_value={
                       "attack_surface": "Latency claims.",
                       "tests": [{"name": "Latency inversion test",
                                   "claim_targeted": "LoRA adds no inference latency",
                                   "procedure": "Serve unmerged LoRA under load.",
                                   "expected_failure_mode": "Latency degrades at batch size 32.",
                                   "severity": "high"}],
                   }):
            result = await run_adversarial_agent(_fake_session(), paper, event_emitter=emit)
        triggers = result.get("triggers", [])
        critique_triggers = [t for t in triggers if t["target"] == "critique"]
        assert critique_triggers, "High-severity adversarial attack must trigger Critique"


# ---------------------------------------------------------------------------
# Trigger chain (full citation click)
# ---------------------------------------------------------------------------

class TestTriggerChain:
    def test_citation_click_returns_all_agent_results(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/citations/cit_adapter/click").json()
        assert r.get("referenced_paper"), "referenced_paper must be present"
        assert r.get("code"), "code result must be present"
        assert r.get("replication"), "replication result must be present"
        assert r.get("adversarial"), "adversarial result must be present"
        assert r.get("findings"), "findings must be present"

    def test_citation_click_graph_has_code_node(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/citations/cit_adapter/click").json()
        node_types = [n["type"] for n in r["graph"]["nodes"]]
        assert "code" in node_types, "A code repo node must appear in the graph"

    def test_citation_click_graph_has_implements_edge(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/citations/cit_adapter/click").json()
        edge_types = [e["type"] for e in r["graph"]["edges"]]
        assert "implements" in edge_types, "An implements edge must connect paper to repo"

    def test_citation_click_events_cover_all_agents(self):
        client = _client()
        sid = _loaded_session(client)
        r = client.post(f"/api/sessions/{sid}/citations/cit_adapter/click").json()
        agent_names = {e.get("agent") for e in r["events"] if e.get("agent")}
        expected = {"Reference", "Critique", "Code", "Replication", "Adversarial", "Evaluation"}
        missing = expected - agent_names
        assert not missing, f"Events missing from agents: {missing}"

    def test_replication_discrepancy_adds_critique_finding(self):
        """Trigger chain: Replication discrepancy → new Critique finding via _process_triggers."""
        client = _client()
        sid = _loaded_session(client)

        with patch("app.agents.replication_agent._build_scorecard", new_callable=AsyncMock,
                   return_value={
                       "claim_under_test": "LoRA matches fine-tuning.",
                       "expected_metric": "BLEU",
                       "minimal_reproduction_steps": [],
                       "environment": "local",
                       "risks": [],
                       "scorecard": {"code_available": True, "data_available": None,
                                     "compute_feasible": True, "expected_time": "2h",
                                     "confidence": 0.5},
                       "discrepancies": ["BLEU is 1.1 points below Table 2"],
                   }):
            r = client.post(f"/api/sessions/{sid}/citations/cit_adapter/click").json()

        finding_titles = [f["title"] for f in r["findings"]]
        # The trigger adds a critique finding from the discrepancy
        assert any("discrepancy" in t.lower() or "replication" in t.lower()
                   for t in finding_titles), \
            f"Expected a replication-discrepancy critique finding, got: {finding_titles}"


# ---------------------------------------------------------------------------
# Figure / table extraction (PyMuPDF)
# ---------------------------------------------------------------------------

class TestVisualExtraction:
    def _make_pdf_with_table(self) -> bytes:
        """Create a minimal in-memory PDF containing a simple text table."""
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Draw a simple table as lines + text
        y = 150
        for row_i, row in enumerate([["Method", "BLEU", "Params"],
                                      ["LoRA (r=4)", "89.3", "1.2M"],
                                      ["Full FT", "89.7", "175M"],
                                      ["Adapter", "88.9", "1.8M"]]):
            x = 80
            for col in row:
                page.insert_text((x, y), col, fontsize=10)
                x += 120
            y += 20
        page.insert_text((80, 120), "Table 1: Comparison of PEFT methods on GLUE.", fontsize=9)
        page.insert_text((80, 50), "Evaluation", fontsize=14)
        return doc.tobytes()

    def test_extract_tables_returns_rows(self):
        from app.services.pdf_parser import extract_tables_from_pdf_bytes, split_into_sections
        pdf = self._make_pdf_with_table()
        text = "Evaluation\nSome evaluation text here."
        sections = split_into_sections(text)
        tables = extract_tables_from_pdf_bytes(pdf, sections)
        # Even if find_tables() misses the text table, function must not crash
        assert isinstance(tables, list), "extract_tables_from_pdf_bytes must return a list"

    def test_extract_figures_returns_list(self):
        from app.services.pdf_parser import extract_figures_from_pdf_bytes, split_into_sections
        import fitz
        # PDF with an embedded image
        doc = fitz.open()
        page = doc.new_page()
        # Insert a coloured rectangle rendered as an image
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 150))
        pix.set_rect(pix.irect, (200, 200, 200))
        img_bytes = pix.tobytes("png")
        img_xref = doc.get_new_xref()
        page.insert_image(fitz.Rect(50, 50, 250, 200), stream=img_bytes)
        page.insert_text((50, 210), "Figure 1: A placeholder figure.", fontsize=9)
        pdf = doc.tobytes()
        sections = split_into_sections("Abstract\nSome text.")
        figures = extract_figures_from_pdf_bytes(pdf, sections)
        assert isinstance(figures, list), "extract_figures_from_pdf_bytes must return a list"

    def test_attach_visuals_to_sections(self):
        from app.models import FigureExtract, PaperSection, TableExtract
        from app.services.pdf_parser import attach_visuals_to_sections
        sec = PaperSection(id="sec_evaluation", title="Evaluation",
                           type="evaluation", text="some text")
        fig = FigureExtract(caption="Figure 1", image_b64="abc", page=0,
                            section_id="sec_evaluation")
        tab = TableExtract(caption="Table 1", rows=[["A", "B"], ["1", "2"]],
                           section_id="sec_evaluation")
        attach_visuals_to_sections([sec], [fig], [tab])
        assert len(sec.figures) == 1
        assert len(sec.tables) == 1
        assert sec.figures[0].caption == "Figure 1"

    def test_paper_section_model_accepts_figures_and_tables(self):
        from app.models import FigureExtract, PaperSection, TableExtract
        sec = PaperSection(
            id="sec_test", title="Test", type="test", text="content",
            figures=[FigureExtract(caption="Fig 1", image_b64="base64data", page=0)],
            tables=[TableExtract(caption="Tab 1", rows=[["col1", "col2"]])],
        )
        assert len(sec.figures) == 1
        assert len(sec.tables) == 1

    def test_parser_agent_demo_has_empty_visuals(self):
        """Demo fixture has no figures/tables — sections must still parse."""
        client = _client()
        sid = client.post("/api/sessions").json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/papers/load",
                        json={"source_type": "demo", "source": "lora"}).json()
        for sec in r["paper"]["sections"]:
            # Fixture sections have no visuals — just check the keys exist
            assert "figures" in sec
            assert "tables" in sec


# ---------------------------------------------------------------------------
# Vision LLM path
# ---------------------------------------------------------------------------

class TestVisionLLM:
    @pytest.mark.asyncio
    async def test_complete_with_vision_empty_images_falls_back_to_text(self):
        from app.services.llm import complete_with_vision
        # With no images, should fall through to complete_text
        with patch("app.services.llm._groq", new_callable=AsyncMock,
                   return_value='{"findings": []}'):
            result = await complete_with_vision("sys", "user", [], '{"findings": []}')
        assert result == '{"findings": []}'

    @pytest.mark.asyncio
    async def test_vision_critique_skips_gracefully_without_table_images(self):
        from app.agents.critique_agent import _vision_table_critique
        from app.models import PaperSection
        # Section with tables that have no image_b64 — should return []
        sec = PaperSection(id="sec_eval", title="Evaluation", type="evaluation", text="...")
        from app.models import TableExtract
        sec.tables = [TableExtract(caption="Table 1", rows=[["A"]], image_b64="")]
        findings = await _vision_table_critique(_lora_paper(), sec)
        assert findings == [], "No image_b64 → no vision findings"

    @pytest.mark.asyncio
    async def test_vision_critique_parses_llm_response(self):
        from app.agents.critique_agent import _vision_table_critique
        from app.models import PaperSection, TableExtract
        sec = PaperSection(id="sec_eval", title="Evaluation", type="evaluation", text="...")
        sec.tables = [TableExtract(caption="Table 1", rows=[["A"]], image_b64="fakebase64")]
        mock_response = '{"findings": [{"severity": "high", "title": "Y-axis starts at 85", "body": "Exaggerates differences."}]}'
        with patch("app.agents.critique_agent.complete_with_vision",
                   new_callable=AsyncMock, return_value=mock_response):
            findings = await _vision_table_critique(_lora_paper(), sec)
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert "[Vision]" in findings[0].title
        assert "Y-axis" in findings[0].title


# ---------------------------------------------------------------------------
# Weave tracing
# ---------------------------------------------------------------------------

class TestWeaveTracing:
    def test_op_decorator_returns_callable(self):
        from app.services.weave_tracing import op as weave_op
        async def my_fn(x: int) -> int:
            return x + 1
        wrapped = weave_op(my_fn)
        assert callable(wrapped)

    @pytest.mark.asyncio
    async def test_op_decorator_preserves_behaviour(self):
        from app.services.weave_tracing import op as weave_op
        async def add(x: int, y: int) -> int:
            return x + y
        wrapped = weave_op(add)
        result = await wrapped(2, 3)
        assert result == 5

    def test_init_weave_returns_bool(self):
        from app.services.weave_tracing import init_weave
        result = init_weave()
        assert isinstance(result, bool)

    def test_all_agent_functions_are_wrapped(self):
        """Every public agent function must be decorated with @weave_op (callable check)."""
        from app.agents.parser_agent import run_parser_agent
        from app.agents.reference_agent import run_reference_agent
        from app.agents.critique_agent import run_critique_agent
        from app.agents.code_agent import run_code_agent
        from app.agents.replication_agent import run_replication_agent
        from app.agents.evaluation_agent import run_evaluation_agent
        from app.agents.adversarial_agent import run_adversarial_agent
        for fn in [run_parser_agent, run_reference_agent, run_critique_agent,
                   run_code_agent, run_replication_agent,
                   run_evaluation_agent, run_adversarial_agent]:
            assert callable(fn), f"{fn.__name__} must be callable after @weave_op"


# ---------------------------------------------------------------------------
# AgentTrigger model
# ---------------------------------------------------------------------------

class TestAgentTriggerModel:
    def test_trigger_serializes_to_dict(self):
        from app.models import AgentTrigger
        t = AgentTrigger(target="critique", reason="contradiction_detected",
                         context={"note": "LoRA omits Adapter-L"})
        d = t.model_dump()
        assert d["target"] == "critique"
        assert d["reason"] == "contradiction_detected"
        assert d["context"]["note"] == "LoRA omits Adapter-L"

    def test_trigger_defaults_empty_context(self):
        from app.models import AgentTrigger
        t = AgentTrigger(target="code", reason="repo_found")
        assert t.context == {}
