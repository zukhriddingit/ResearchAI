from __future__ import annotations

from typing import Any

from app.models import Paper


async def run_adversarial_agent(session, paper: Paper, repo=None, event_emitter=None) -> dict[str, Any]:
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
            {
                "name": "OOD and code-task transfer test",
                "claim_targeted": "LoRA generalizes as a strong parameter-efficient adaptation method.",
                "procedure": "Evaluate on out-of-distribution prompts, long-context tasks, and code-generation tasks not emphasized by the main benchmark set.",
                "expected_failure_mode": "Quality parity may only hold for the benchmark mix used in the paper.",
                "severity": "medium",
            },
            {
                "name": "Compute and memory edge-case test",
                "claim_targeted": "LoRA reduces GPU memory and storage costs.",
                "procedure": "Measure peak memory, optimizer state, checkpoint size, and tokens/sec across small and large batch sizes.",
                "expected_failure_mode": "Memory savings may be diluted by optimizer, activation, or serving overheads.",
                "severity": "medium",
            },
            {
                "name": "Baseline omission audit",
                "claim_targeted": "LoRA outperforms or matches other parameter-efficient baselines.",
                "procedure": "Check whether adapters, prefix tuning, and full fine-tuning use matched data, model size, tuning budget, and hardware.",
                "expected_failure_mode": "Unmatched baseline settings can make LoRA's advantage look larger than it is.",
                "severity": "high",
            },
        ],
    }
    if event_emitter:
        for test in result["tests"]:
            event_emitter(session.session_id, "attack.found", test["name"], agent="Adversarial", status=test["severity"], payload=test)
        event_emitter(session.session_id, "agent.finished", "Adversarial Agent proposed stress tests.", agent="Adversarial", status="done")
    return result
