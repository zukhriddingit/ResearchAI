from __future__ import annotations

from app.models import AgentFinding, Paper


async def run_evaluation_agent(session, paper: Paper, section=None, event_emitter=None) -> list[AgentFinding]:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Evaluation Agent started.", agent="Evaluation", status="running")

    section_id = section.id if section else _evaluation_section_id(paper)
    findings = [
        AgentFinding(
            id="finding_missing_latency_benchmark",
            agent="Evaluation",
            severity="medium",
            title="Missing matched serving latency benchmark",
            body="The main paper's no-latency claim should be evaluated with merged LoRA, unmerged LoRA, adapters, and full fine-tuning under identical batching and hardware.",
            related_paper_id=paper.id,
            related_section_id=section_id,
            related_claim_id="claim_latency",
        ),
        AgentFinding(
            id="finding_missing_rank_ablation",
            agent="Evaluation",
            severity="medium",
            title="Missing rank sensitivity ablation",
            body="A replication plan should sweep LoRA rank values and report quality, trainable parameters, memory, and throughput to show where the efficiency tradeoff breaks.",
            related_paper_id=paper.id,
            related_section_id=section_id,
            related_claim_id="claim_quality",
        ),
        AgentFinding(
            id="finding_ood_code_benchmark",
            agent="Evaluation",
            severity="medium",
            title="Benchmark coverage gap",
            body="LoRA should be evaluated on harder OOD, long-context, and code-generation workloads before generalizing the quality claim beyond the reported tasks.",
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
            event_type = "experiment.missing" if finding.id.startswith("finding_missing") else "benchmark.suggested"
            event_emitter(
                session.session_id,
                event_type,
                finding.title,
                agent="Evaluation",
                status=finding.severity,
                payload=finding.model_dump(),
            )
        event_emitter(session.session_id, "agent.finished", "Evaluation Agent suggested benchmarks.", agent="Evaluation", status="done")
    return findings


def _evaluation_section_id(paper: Paper) -> str:
    for section in paper.sections:
        if section.type == "evaluation" or "evaluation" in section.title.lower() or "experiment" in section.title.lower():
            return section.id
    return paper.sections[-1].id if paper.sections else "sec_evaluation"
