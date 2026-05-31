from __future__ import annotations

from app.models import AgentFinding, Paper


async def run_evaluation_agent(session, paper: Paper, section=None, event_emitter=None) -> list[AgentFinding]:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Evaluation Agent started.", agent="Evaluation", status="running")

    section_id = section.id if section else "sec_evaluation"
    findings = [
        AgentFinding(
            id="finding_benchmark_coverage",
            agent="Evaluation",
            severity="medium",
            title="Benchmark coverage gap",
            body="LoRA should be evaluated on harder OOD and long-context workloads before generalizing the quality claim.",
            related_paper_id=paper.id,
            related_section_id=section_id,
        ),
        AgentFinding(
            id="finding_metric_pairing",
            agent="Evaluation",
            severity="low",
            title="Pair quality metrics with systems metrics",
            body="The evaluation should pair task quality with trainable parameters, memory, and tokens/sec so the efficiency claim is directly visible.",
            related_paper_id=paper.id,
            related_section_id=section_id,
        ),
    ]
    if event_emitter:
        for finding in findings:
            event_emitter(session.session_id, "benchmark.suggested", finding.title, agent="Evaluation", status=finding.severity, payload=finding.model_dump())
        event_emitter(session.session_id, "agent.finished", "Evaluation Agent suggested benchmarks.", agent="Evaluation", status="done")
    return findings

