from __future__ import annotations

from app.models import AgentFinding, Paper, new_id
from app.services.llm import complete_json, reasoning_model


EVALUATION_PROMPT = """You are the Evaluation Agent for DeepPaper.
Use a reasoning model to design a stronger evaluation plan for the paper.
Focus on what a real researcher would need next: missing baselines, ablations, datasets,
metrics, statistical checks, compute budgets, and failure-mode tests.

Return JSON:
{
  "findings": [
    {
      "severity": "low|medium|high",
      "title": "specific evaluation gap",
      "body": "why it matters and exactly how to test it"
    }
  ]
}"""


async def run_evaluation_agent(session, paper: Paper, section=None, event_emitter=None) -> list[AgentFinding]:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Evaluation Agent started.", agent="Evaluation", status="running")

    section_id = section.id if section else _evaluation_section_id(paper)
    findings = [
        AgentFinding(
            id=new_id("finding"),
            agent="Evaluation",
            severity="medium",
            title="Missing matched baseline benchmark",
            body="The main paper should be evaluated against baselines under identical data, model scale, compute budget, and reporting conditions.",
            related_paper_id=paper.id,
            related_section_id=section_id,
        ),
        AgentFinding(
            id=new_id("finding"),
            agent="Evaluation",
            severity="medium",
            title="Missing component ablation",
            body="A replication plan should isolate the proposed method from architecture size, training schedule, data augmentation, and implementation details.",
            related_paper_id=paper.id,
            related_section_id=section_id,
        ),
        AgentFinding(
            id=new_id("finding"),
            agent="Evaluation",
            severity="medium",
            title="Benchmark coverage gap",
            body="The reported evaluation should be extended to harder out-of-distribution or stress-test settings before generalizing the strongest claims.",
            related_paper_id=paper.id,
            related_section_id=section_id,
        ),
        AgentFinding(
            id=new_id("finding"),
            agent="Evaluation",
            severity="low",
            title="Pair quality metrics with resource metrics",
            body="The evaluation should pair task quality with compute, memory, latency, and parameter counts so tradeoffs are directly visible.",
            related_paper_id=paper.id,
            related_section_id=section_id,
        ),
    ]
    fallback = {"findings": [finding.model_dump() for finding in findings]}
    llm_result = await complete_json(
        EVALUATION_PROMPT,
        (
            f"Paper: {paper.title}\n"
            f"Abstract: {paper.abstract or ''}\n"
            f"Evaluation text: {(section.text if section else ' '.join(s.text for s in paper.sections if s.type in {'evaluation', 'experiments', 'results'}))[:3500]}\n"
            "Return JSON: {\"findings\": [{\"severity\":\"low|medium|high\", \"title\":\"...\", \"body\":\"...\"}]}"
        ),
        fallback,
        model=reasoning_model(),
        temperature=0.2,
        max_tokens=800,
    )
    findings = _parse_findings(llm_result, fallback, paper.id, section_id)
    if event_emitter:
        event_emitter(
            session.session_id,
            "evaluation.plan",
            f"Evaluation Agent produced {len(findings)} benchmark improvement(s).",
            agent="Evaluation",
            status="done",
            payload={"findings": [finding.model_dump() for finding in findings], "model": reasoning_model()},
        )
        for finding in findings:
            lower_finding = f"{finding.title} {finding.body}".lower()
            event_type = "experiment.missing" if "missing" in lower_finding or "ablation" in lower_finding else "benchmark.suggested"
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


def _parse_findings(result: dict, fallback: dict, paper_id: str, section_id: str) -> list[AgentFinding]:
    raw_findings = result.get("findings")
    if not isinstance(raw_findings, list):
        raw_findings = fallback["findings"]
    findings: list[AgentFinding] = []
    for item in raw_findings[:4]:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity") if item.get("severity") in {"low", "medium", "high"} else "medium"
        findings.append(
            AgentFinding(
                id=str(item.get("id") or new_id("finding")),
                agent="Evaluation",
                severity=severity,
                title=str(item.get("title") or "Benchmark suggestion"),
                body=str(item.get("body") or "Add a benchmark that better tests the paper's main claim."),
                related_paper_id=str(item.get("related_paper_id") or paper_id),
                related_section_id=str(item.get("related_section_id") or section_id),
            )
        )
    return findings or [AgentFinding.model_validate(item) for item in fallback["findings"]]


def _evaluation_section_id(paper: Paper) -> str:
    for section in paper.sections:
        if section.type == "evaluation" or "evaluation" in section.title.lower() or "experiment" in section.title.lower():
            return section.id
    return paper.sections[-1].id if paper.sections else "sec_evaluation"
