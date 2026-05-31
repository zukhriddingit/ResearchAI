from fastapi.testclient import TestClient

from app.main import app


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
    assert len(clicked["graph"]["nodes"]) >= 3
    assert len(clicked["graph"]["edges"]) >= 2

    critique = client.post(
        f"/api/sessions/{session_id}/agents/critique/run",
        json={"paper_id": "paper_lora_main", "mode": "manual"},
    ).json()
    assert critique["findings"]

