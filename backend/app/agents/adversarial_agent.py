from __future__ import annotations

from app.models import Paper


async def run_adversarial_agent(session, paper: Paper, repo=None, event_emitter=None) -> dict:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Adversarial Agent started.", agent="Adversarial", status="running")

    result = {
        "attack_surface": "Claims around no latency, rank selection, and broad benchmark generalization.",
        "tests": [
            {
                "name": "Rank sensitivity stress test",
                "claim_targeted": "LoRA reaches competitive quality with few trainable parameters.",
                "procedure": "Sweep rank values under fixed compute and compare quality, memory, and tokens/sec.",
                "expected_failure_mode": "Very low ranks may underfit while high ranks reduce the efficiency advantage.",
                "severity": "medium",
            },
            {
                "name": "Matched serving latency test",
                "claim_targeted": "LoRA adds no inference latency after merge.",
                "procedure": "Serve merged LoRA, unmerged LoRA, and adapter baselines with identical batching.",
                "expected_failure_mode": "Serving implementation details may erase or invert the latency gap.",
                "severity": "high",
            },
        ],
    }
    if event_emitter:
        for test in result["tests"]:
            event_emitter(session.session_id, "attack.found", test["name"], agent="Adversarial", status=test["severity"], payload=test)
        event_emitter(session.session_id, "agent.finished", "Adversarial Agent proposed stress tests.", agent="Adversarial", status="done")
    return result

