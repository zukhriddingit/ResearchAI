import sys
import os
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DEEPPAPER_DISABLE_EXTERNAL"] = "1"

from app.main import app


def main() -> None:
    client = TestClient(app)
    health = client.get("/health")
    health.raise_for_status()
    session = client.post("/api/sessions").json()
    session_id = session["session_id"]
    loaded = client.post(
        f"/api/sessions/{session_id}/papers/load",
        json={"source_type": "demo", "source": "lora"},
    )
    loaded.raise_for_status()
    clicked = client.post(f"/api/sessions/{session_id}/citations/cit_adapter/click")
    clicked.raise_for_status()
    result = clicked.json()
    upload_text = (
        "2602.10067v3 [cs.LG] 19 Feb 2026\n"
        "Grounding Supervision in Language Features\n"
        "Mina Park, Lucas Chen, Aria Patel\n\n"
        "Abstract\n"
        "We propose a quick uploaded paper check. It improves confidence in the PDF and text upload flow.\n\n"
        "Methodology\n"
        "The method references prior work [1] and creates a parsed session.\n\n"
        "References\n"
        "[1] A smoke fixture reference."
    )
    uploaded = client.post(
        f"/api/sessions/{session_id}/papers/upload",
        files={"file": ("2602.10067v3 (1).txt", upload_text.encode("utf-8"), "text/plain")},
    )
    uploaded.raise_for_status()
    print(
        {
            "session_id": session_id,
            "paper": result["referenced_paper"]["title"],
            "nodes": len(result["graph"]["nodes"]),
            "events": len(result["events"]),
            "upload": uploaded.json()["paper"]["title"],
        }
    )


if __name__ == "__main__":
    main()
