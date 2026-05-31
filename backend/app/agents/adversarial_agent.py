from __future__ import annotations

from app.models import AgentTrigger, Paper
from app.services.llm import complete_json
from app.services.weave_tracing import op as weave_op


ADVERSARIAL_PROMPT = """\
You are a red-teamer for research papers. Given a paper's claims and methodology, design specific adversarial stress tests that could break each claim.

Return JSON:
{
  "attack_surface": "...",
  "tests": [
    {
      "name": "...",
      "claim_targeted": "...",
      "procedure": "...",
      "expected_failure_mode": "...",
      "severity": "low" | "medium" | "high"
    }
  ]
}

Focus on:
- Hyperparameter sensitivity (e.g. rank sweep for LoRA)
- OOD inputs not covered by the paper's benchmarks
- Edge cases in the described algorithm
- Adversarial inputs (if the paper involves a model that processes text/images)
- Implementation gaps that could produce different results than claimed

Return 2-4 tests. Be concrete — name specific parameter values and expected breakpoints."""


@weave_op
async def run_adversarial_agent(
    session, paper: Paper, repo=None, event_emitter=None
) -> dict:
    """
    Propose adversarial stress tests to actively break the paper's key claims.

    Triggers emitted:
        → critique: each high-severity attack becomes a critique finding
        → code:     test cases to add to the repo's test suite
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Adversarial Agent started.",
                      agent="Adversarial", status="running")

    result = await _design_attacks(paper, repo)

    triggers: list[dict] = []
    for test in result.get("tests", []):
        if test.get("severity") in ("high", "medium"):
            triggers.append(AgentTrigger(
                target="critique",
                reason="adversarial_attack_found",
                context={"attack_name": test["name"], "claim_targeted": test["claim_targeted"],
                         "failure_mode": test["expected_failure_mode"]},
            ).model_dump())
        triggers.append(AgentTrigger(
            target="code",
            reason="test_case_needed",
            context={"test_name": test["name"], "procedure": test["procedure"]},
        ).model_dump())

    result["triggers"] = triggers

    if event_emitter:
        for test in result.get("tests", []):
            event_emitter(session.session_id, "attack.found", test["name"],
                          agent="Adversarial", status=test["severity"], payload=test)
        event_emitter(session.session_id, "agent.finished",
                      f"Adversarial Agent proposed {len(result.get('tests', []))} stress tests.",
                      agent="Adversarial", status="done")
    return result


@weave_op
async def _design_attacks(paper: Paper, repo) -> dict:
    claims_text = " | ".join(c.text for c in paper.claims[:4]) if paper.claims else "No claims extracted."
    method_text = next((s.text[:1500] for s in paper.sections
                        if s.type in ("methodology", "method", "approach")), "")
    repo_name = repo.get("full_name", "N/A") if repo else "N/A"
    user_msg = (
        f"Paper: {paper.title}\nClaims: {claims_text}\n"
        f"Methodology excerpt: {method_text}\nRepo: {repo_name}"
    )
    fallback = {
        "attack_surface": "Claims around no latency, rank selection, and broad benchmark generalization.",
        "tests": [
            {
                "name": "Rank sensitivity stress test",
                "claim_targeted": "LoRA reaches competitive quality with few trainable parameters.",
                "procedure": "Sweep rank r ∈ {1, 2, 4, 8, 16, 32, 64} under fixed compute budget; measure quality, memory, and tokens/sec.",
                "expected_failure_mode": "r=1 underfits on code tasks; r=64 erodes efficiency advantage.",
                "severity": "medium",
            },
            {
                "name": "Matched serving latency test",
                "claim_targeted": "LoRA adds no inference latency after merge.",
                "procedure": "Serve merged LoRA, unmerged LoRA, and adapter baselines with identical batching and hardware.",
                "expected_failure_mode": "Serving implementation details may erase or invert the latency gap.",
                "severity": "high",
            },
        ],
    }
    return await complete_json(ADVERSARIAL_PROMPT, user_msg, fallback)
