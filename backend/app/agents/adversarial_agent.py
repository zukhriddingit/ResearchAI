from __future__ import annotations

from typing import Any

from app.models import Paper
from app.services.llm import complete_json, reasoning_model


ADVERSARIAL_PROMPT = """You are the Adversarial Agent for DeepPaper.
Create stress tests that could falsify or weaken the main paper's strongest claims.
Keep the tests concrete enough for a Code or Replication Agent to scaffold."""


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
    result = await complete_json(
        ADVERSARIAL_PROMPT,
        (
            f"Paper: {paper.title}\n"
            f"Abstract: {paper.abstract or ''}\n"
            f"Claims: {[claim.text for claim in paper.claims]}\n"
            "Return JSON with attack_surface and tests. Each test needs name, claim_targeted, "
            "procedure, expected_failure_mode, and severity low|medium|high."
        ),
        result,
        model=reasoning_model(),
        temperature=0.25,
        max_tokens=900,
    )
    if event_emitter:
        tests = result.get("tests") if isinstance(result.get("tests"), list) else []
        for test in tests:
            if not isinstance(test, dict):
                continue
            event_emitter(
                session.session_id,
                "attack.found",
                str(test.get("name") or "Adversarial stress test"),
                agent="Adversarial",
                status=str(test.get("severity") or "medium"),
                payload=test,
            )
        event_emitter(session.session_id, "agent.finished", "Adversarial Agent proposed stress tests.", agent="Adversarial", status="done")
    return result
