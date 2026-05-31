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
        "attack_surface": "Claims around quality, efficiency, robustness, and benchmark generalization.",
        "tests": [
            {
                "name": "Matched baseline stress test",
                "claim_targeted": "The proposed method outperforms or matches prior approaches.",
                "procedure": "Rerun the closest baselines with matched data, model scale, training budget, and hardware.",
                "expected_failure_mode": "Unmatched baseline settings can make the reported advantage look larger than it is.",
                "severity": "medium",
            },
            {
                "name": "Ablation removal test",
                "claim_targeted": "The proposed component is responsible for the reported gain.",
                "procedure": "Remove or replace the proposed component while keeping the rest of the pipeline fixed.",
                "expected_failure_mode": "The gain may come from training schedule, scale, or implementation details rather than the claimed mechanism.",
                "severity": "high",
            },
            {
                "name": "Out-of-distribution transfer test",
                "claim_targeted": "The method generalizes beyond the reported benchmark mix.",
                "procedure": "Evaluate on shifted datasets, harder examples, and settings not emphasized by the main benchmark set.",
                "expected_failure_mode": "Quality parity may only hold for the benchmark mix used in the paper.",
                "severity": "medium",
            },
            {
                "name": "Compute and memory edge-case test",
                "claim_targeted": "The method is efficient enough to be practical.",
                "procedure": "Measure peak memory, wall-clock time, throughput, and failure rates across small and large batch sizes.",
                "expected_failure_mode": "Resource savings may disappear under realistic serving or training conditions.",
                "severity": "medium",
            },
            {
                "name": "Baseline omission audit",
                "claim_targeted": "The paper compares against the right prior work.",
                "procedure": "Check whether recent and task-specific baselines are missing from the comparison table.",
                "expected_failure_mode": "A missing strong baseline can change the conclusion.",
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
