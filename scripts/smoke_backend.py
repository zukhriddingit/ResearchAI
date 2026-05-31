import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

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
    print(
        {
            "session_id": session_id,
            "paper": result["referenced_paper"]["title"],
            "nodes": len(result["graph"]["nodes"]),
            "events": len(result["events"]),
        }
    )


if __name__ == "__main__":
    main()
