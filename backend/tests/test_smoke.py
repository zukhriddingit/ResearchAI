import os

from fastapi.testclient import TestClient

os.environ["DEEPPAPER_DISABLE_EXTERNAL"] = "1"

from app.main import app
from app.services import weave_tracing


client = TestClient(app)


def test_demo_flow():
    assert client.get("/health").json()["ok"] is True
    session = client.post("/api/sessions").json()
    session_id = session["session_id"]

    loaded = client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    ).json()
    assert loaded["paper"]["id"] == "paper_lora_main"
    assert len(loaded["paper"]["sections"]) >= 4
    assert len(loaded["paper"]["citations"]) >= 4

    clicked = client.post(f"/api/sessions/{session_id}/citations/cit_adapter/click").json()
    assert clicked["referenced_paper"]["id"] == "paper_adapters"
    assert len(clicked["graph"]["nodes"]) >= 2
    assert len(clicked["graph"]["edges"]) >= 1
    clicked_event_types = {event["type"] for event in clicked["events"]}
    assert "citation.resolved" in clicked_event_types

    critique = client.post(
        f"/api/sessions/{session_id}/agents/critique/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert critique["findings"]

    code = client.post(
        f"/api/sessions/{session_id}/agents/code/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert code["output"]["repo"]["full_name"]
    assert any(event["type"] == "repo.ready" for event in code["events"])

    replication = client.post(
        f"/api/sessions/{session_id}/agents/replication/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert replication["output"]["scorecard"]
    assert any(event["type"] == "replication.queued" for event in replication["events"])

    evaluation = client.post(
        f"/api/sessions/{session_id}/agents/evaluation/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    evaluation_event_types = {event["type"] for event in evaluation["events"]}
    assert "benchmark.suggested" in evaluation_event_types
    assert "experiment.missing" in evaluation_event_types

    adversarial = client.post(
        f"/api/sessions/{session_id}/agents/adversarial/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert any(event["type"] == "attack.found" for event in adversarial["events"])


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
