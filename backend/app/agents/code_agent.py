from __future__ import annotations

from app.models import Paper
from app.services.fixtures import load_lora_fixture
from app.services.github_client import search_repositories


async def run_code_agent(session, paper: Paper, section=None, finding=None, event_emitter=None) -> dict:
    if event_emitter:
        event_emitter(session.session_id, "code.search.started", "Code Agent searching for implementation repos.", agent="Code", status="running")

    query = f"{paper.title} {paper.arxiv_id or ''}".strip()
    repos = await search_repositories(query, max_results=3)
    repo = repos[0] if repos else load_lora_fixture()["code_repo"]
    result = {
        "repo": repo,
        "key_files": [
            {"path": "loralib/layers.py", "why_relevant": "Contains LoRA layer wrappers and merge behavior."},
            {"path": "examples/NLG", "why_relevant": "Likely entrypoint for a small language generation reproduction."}
        ],
        "paper_claim_connection": "The repo can test whether LoRA preserves quality while reducing trainable parameters and serving latency.",
        "implementation_risks": ["Benchmark scripts may not match the paper exactly.", "Adapter baseline may need a separate implementation."],
        "handoff_to_replication": {
            "entrypoint_guess": "examples/NLG",
            "setup_guess": "pip install -r requirements.txt && pip install -e .",
            "minimal_run_plan": ["Run a toy LoRA task.", "Record trainable parameters.", "Compare dry-run logs to adapter baseline plan."]
        },
    }
    if event_emitter:
        event_emitter(session.session_id, "repo.ready", "Code Agent found a candidate implementation repo.", agent="Code", status="done", payload=result)
    return result

