import os

from fastapi.testclient import TestClient

os.environ["DEEPPAPER_DISABLE_EXTERNAL"] = "1"
os.environ["GITHUB_TOKEN"] = ""
os.environ["SEMANTIC_SCHOLAR_API_KEY"] = ""

from app.main import app
from app.services import weave_tracing
from app.services.pdf_parser import split_into_sections


client = TestClient(app)


def test_uploaded_paper_agent_flow():
    assert client.get("/health").json()["ok"] is True
    session = client.post("/api/sessions").json()
    session_id = session["session_id"]
    text = (
        "A Small Vision Paper\n"
        "Alex Researcher\n\n"
        "Abstract\n"
        "We propose a compact model that improves accuracy while reducing compute.\n\n"
        "1. Introduction\n"
        "The paper cites prior work [1] and frames the main problem.\n\n"
        "2. Method\n"
        "The method introduces a new attention block and reports efficiency improvements.\n\n"
        "References\n"
        "[1] Jane Doe and John Smith. A Useful Baseline for Vision Models. In TestConf, 2020."
    )

    uploaded = client.post(
        f"/api/sessions/{session_id}/papers/upload",
        files={"file": ("small-vision-paper.txt", text.encode("utf-8"), "text/plain")},
    ).json()
    paper = uploaded["paper"]
    paper_id = paper["id"]
    citation_id = paper["citations"][0]["id"]
    assert paper["title"] == "A Small Vision Paper"
    assert len(paper["sections"]) >= 3
    assert len(paper["citations"]) == 1

    clicked = client.post(f"/api/sessions/{session_id}/citations/{citation_id}/click", params={"paper_id": paper_id}).json()
    assert clicked["referenced_paper"]["title"] == "A Useful Baseline for Vision Models"
    assert len(clicked["graph"]["nodes"]) >= 2
    assert len(clicked["graph"]["edges"]) >= 1
    clicked_event_types = {event["type"] for event in clicked["events"]}
    assert "citation.resolved" in clicked_event_types
    referenced_paper_id = clicked["referenced_paper"]["id"]

    promoted = client.post(f"/api/sessions/{session_id}/papers/{referenced_paper_id}/analyze").json()
    assert promoted["session_id"] != session_id
    assert promoted["main_paper_id"] == referenced_paper_id
    promoted_papers = {paper["id"]: paper for paper in promoted["papers"]}
    promoted_nodes = {node["paper_id"]: node for node in promoted["graph"]["nodes"] if node.get("paper_id")}
    assert promoted_papers[referenced_paper_id]["is_main"] is True
    assert promoted_papers[paper_id]["is_main"] is False
    assert promoted_nodes[referenced_paper_id]["status"] == "main"
    assert promoted_nodes[paper_id]["status"] == "referenced"
    assert len(promoted["graph"]["edges"]) >= 1

    critique = client.post(
        f"/api/sessions/{session_id}/agents/critique/run",
        json={"paper_id": paper_id, "mode": "manual"},
    ).json()
    assert critique["findings"]

    code = client.post(
        f"/api/sessions/{session_id}/agents/code/run",
        json={"paper_id": paper_id, "mode": "manual"},
    ).json()
    assert code["output"]["repo"]["full_name"]
    assert any(event["type"] == "repo.ready" for event in code["events"])

    replication = client.post(
        f"/api/sessions/{session_id}/agents/replication/run",
        json={"paper_id": paper_id, "mode": "manual"},
    ).json()
    assert replication["output"]["scorecard"]
    assert any(event["type"] == "replication.queued" for event in replication["events"])

    evaluation = client.post(
        f"/api/sessions/{session_id}/agents/evaluation/run",
        json={"paper_id": paper_id, "mode": "manual"},
    ).json()
    evaluation_event_types = {event["type"] for event in evaluation["events"]}
    assert "benchmark.suggested" in evaluation_event_types
    assert "experiment.missing" in evaluation_event_types

    adversarial = client.post(
        f"/api/sessions/{session_id}/agents/adversarial/run",
        json={"paper_id": paper_id, "mode": "manual"},
    ).json()
    assert any(event["type"] == "attack.found" for event in adversarial["events"])


def test_numbered_sections_ignore_table_method_headers():
    text = (
        "Vision Transformer with Deformable Attention\n\n"
        "Abstract\n"
        "The abstract explains the paper.\n\n"
        "1. Introduction\n"
        "The introduction cites prior work [1].\n\n"
        "2. Related Work\n"
        "Related work text.\n\n"
        "4.2. COCO Object Detection\n"
        "COCO experiment text.\n"
        "ImageNet-1K Classification\n"
        "Method\n"
        "Resolution FLOPs #Param Top-1 Acc.\n"
        "DAT-T 224 4.6G 29M 82.0\n\n"
        "5. Conclusion\n"
        "Conclusion text.\n\n"
        "References\n"
        "[1] A reference title."
    )
    sections = split_into_sections(text)
    titles = [section.title for section in sections]
    assert "Introduction" in titles
    assert "COCO Object Detection" in titles
    assert titles.count("Method") == 0


def test_weave_noop_without_env(monkeypatch):
    monkeypatch.delenv("WEAVE_PROJECT", raising=False)
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    weave_tracing._initialized = False
    weave_tracing._weave = None

    assert weave_tracing.init_weave() is False
    weave_tracing.trace_agent_run("Test", {"input": True}, {"output": True})
    weave_tracing.log_event({"type": "noop"})


def test_text_upload_flow():
    session = client.post("/api/sessions").json()
    session_id = session["session_id"]
    text = (
        "2602.10067v3 [cs.LG] 19 Feb 2026\n"
        "Grounding Supervision in Language Features\n"
        "Mina Park, Lucas Chen, Aria Patel\n\n"
        "Abstract\n"
        "We propose a tiny upload test paper for DeepPaper. It improves the demo upload flow.\n\n"
        "Methodology\n"
        "The method cites prior work [1] and checks that uploaded text becomes sections.\n\n"
        "References\n"
        "[1] A small fixture reference."
    )
    uploaded = client.post(
        f"/api/sessions/{session_id}/papers/upload",
        files={"file": ("2602.10067v3 (1).txt", text.encode("utf-8"), "text/plain")},
    ).json()
    assert uploaded["paper"]["title"] == "Grounding Supervision in Language Features"
    assert uploaded["graph"]["nodes"][0]["label"] == "Grounding Supervision in Language Features"
    assert uploaded["paper"]["sections"]
    assert uploaded["graph"]["nodes"]
