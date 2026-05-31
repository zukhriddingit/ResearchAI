from __future__ import annotations

from app.models import AgentFinding, AgentTrigger, Paper, new_id
from app.services.llm import complete_json
from app.services.weave_tracing import op as weave_op


EVALUATION_PROMPT = """\
You are a benchmark evaluation expert. Given a research paper's evaluation section, suggest better or missing benchmarks.

Return JSON:
{
  "findings": [
    {
      "severity": "low" | "medium" | "high",
      "title": "...",
      "body": "...",
      "suggested_benchmark": "...",
      "why_relevant": "..."
    }
  ]
}

Consider:
- Are these benchmarks still the best ones today, or have harder / more relevant ones been released?
- Are OOD, long-context, or cross-lingual benchmarks missing?
- Does the paper cherry-pick only benchmarks where it performs best?
- Are systems metrics (latency, throughput, memory) paired with quality metrics?

Return 2-3 findings. Be specific to the paper."""


@weave_op
async def run_evaluation_agent(
    session, paper: Paper, section=None, event_emitter=None
) -> list[AgentFinding]:
    """
    Suggest missing or better benchmarks for the paper's evaluation.

    Triggers emitted:
        → code: for each benchmark suggestion (scaffold evaluation harness)
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Evaluation Agent started.",
                      agent="Evaluation", status="running")

    findings = await _suggest_benchmarks(paper, section)

    triggers: list[dict] = []
    for f in findings:
        bench = f.body  # use body as context for code scaffolding
        triggers.append(AgentTrigger(
            target="code",
            reason="benchmark_harness_needed",
            context={"finding_id": f.id, "benchmark_context": bench[:200]},
        ).model_dump())

    if event_emitter:
        for finding in findings:
            event_emitter(session.session_id, "benchmark.suggested", finding.title,
                          agent="Evaluation", status=finding.severity, payload=finding.model_dump())
        event_emitter(session.session_id, "agent.finished",
                      f"Evaluation Agent suggested {len(findings)} benchmark improvements.",
                      agent="Evaluation", status="done",
                      payload={"findings": len(findings), "triggers": triggers})

    # Attach triggers to return via a side-channel attribute (so the list type stays clean)
    for f in findings:
        object.__setattr__(f, "_triggers", triggers)  # type: ignore[arg-type]

    return findings


@weave_op
async def _suggest_benchmarks(paper: Paper, section) -> list[AgentFinding]:
    section_id = section.id if section else "sec_evaluation"
    eval_text = section.text if section else (
        next((s.text for s in paper.sections if "eval" in s.type or "result" in s.type), "")
    )
    user_msg = (
        f"Paper: {paper.title}\n"
        f"Year: {paper.year or 'unknown'}\n"
        f"Evaluation text:\n{eval_text[:2500]}"
    )
    fallback = {"findings": [
        {"severity": "medium", "title": "Benchmark coverage gap",
         "body": "LoRA should be evaluated on harder OOD and long-context workloads before generalizing the quality claim.",
         "suggested_benchmark": "HELM or BigBench Hard", "why_relevant": "Harder distribution shifts"},
        {"severity": "low", "title": "Pair quality metrics with systems metrics",
         "body": "The evaluation should pair task quality with trainable parameters, memory, and tokens/sec.",
         "suggested_benchmark": "MLPerf Inference", "why_relevant": "Efficiency claims need systems benchmarks"},
    ]}
    result = await complete_json(EVALUATION_PROMPT, user_msg, fallback)
    raw = result.get("findings", fallback["findings"])

    findings: list[AgentFinding] = []
    for item in (raw or fallback["findings"])[:3]:
        if not isinstance(item, dict):
            continue
        findings.append(AgentFinding(
            id=new_id("finding"),
            agent="Evaluation",
            severity=item.get("severity", "medium"),
            title=str(item.get("title", "Benchmark suggestion"))[:120],
            body=str(item.get("body", ""))[:600],
            related_paper_id=paper.id,
            related_section_id=section_id,
        ))
    return findings or [
        AgentFinding(id="finding_benchmark_coverage", agent="Evaluation", severity="medium",
                     title="Benchmark coverage gap", body=fallback["findings"][0]["body"],
                     related_paper_id=paper.id, related_section_id=section_id),
        AgentFinding(id="finding_metric_pairing", agent="Evaluation", severity="low",
                     title="Pair quality metrics with systems metrics", body=fallback["findings"][1]["body"],
                     related_paper_id=paper.id, related_section_id=section_id),
    ]
