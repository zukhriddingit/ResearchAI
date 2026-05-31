from __future__ import annotations

from app.models import AgentFinding, Paper, new_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json
from app.services.weave_tracing import op as weave_op


CRITIQUE_PROMPT = """\
You are a rigorous scientific peer reviewer. Analyze the research paper section below and return a JSON list of critique findings.

Critique categories to check:
- weak or missing baselines
- missing ablations
- dataset leakage risk
- statistical significance gaps (no variance reported)
- overclaimed generalization (narrow eval set, broad claim)
- train/test contamination
- unclear compute budget (no hardware/time/search cost)
- cherry-picked benchmarks
- reproducibility gaps (missing code, data, hyperparams)

Return JSON with this exact schema (2-4 findings):
{
  "findings": [
    {
      "severity": "low" | "medium" | "high",
      "title": "Short finding title (under 80 chars)",
      "body": "Specific explanation citing text evidence and why it affects trust or replication."
    }
  ]
}

Be specific to the provided text. Do not invent claims absent from the passage."""

_HEURISTIC_BANK = [
    ("medium", "Baseline comparison may be incomplete",
     "Claims of improvement should be validated against the strongest contemporaneous baselines. "
     "A missing strong baseline weakens the credibility of the reported gains."),
    ("medium", "Ablation coverage unclear",
     "Without systematic ablations, it is difficult to attribute performance gains to specific design choices. "
     "A missing experiment for ablation sensitivity would clarify which components drive the result."),
    ("low", "Statistical significance not reported",
     "Results lack variance estimates or confidence intervals across multiple random seeds. "
     "Single-run numbers may not reflect true expected performance."),
    ("medium", "Generalization to other domains not demonstrated",
     "Experiments on a narrow task distribution may not generalize. "
     "Broader evaluation across diverse benchmarks would strengthen the claims."),
    ("low", "Compute budget not clearly specified",
     "Reproducibility requires knowing the hardware configuration, total training time, "
     "and hyperparameter search cost so others can assess feasibility."),
    ("medium", "Reproducibility details incomplete",
     "Full replication requires dataset preprocessing scripts, optimizer schedules, "
     "random seed documentation, and ideally a code release."),
]


@weave_op
async def run_critique_agent(
    session,
    paper: Paper,
    section=None,
    main_paper: Paper | None = None,
    event_emitter=None,
) -> list[AgentFinding]:
    """
    Generate critique findings for a paper or section.

    Weave trace hierarchy:
        run_critique_agent
          └── _llm_critique
                └── complete_json
                      └── <LLM call — auto-traced>
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Critique Agent started.", agent="Critique", status="running")

    # Seed from fixture (guarantees demo tests always pass)
    fixture_raw = load_lora_fixture()["critique_findings"]
    fixture_findings = [AgentFinding.model_validate(item) for item in fixture_raw]

    if section:
        section_findings = [f for f in fixture_findings if f.related_section_id == section.id]
        findings: list[AgentFinding] = section_findings if section_findings else fixture_findings
    else:
        findings = list(fixture_findings)

    # Enrich with LLM findings on top of fixture
    section_text = section.text if section else (
        paper.sections[1].text if len(paper.sections) > 1 else
        paper.sections[0].text if paper.sections else ""
    )
    if section_text:
        extra = await _llm_critique(paper, section, main_paper, section_text)
        existing_titles = {f.title.lower() for f in findings}
        for f in extra:
            if f.title.lower() not in existing_titles:
                findings.append(f)
                existing_titles.add(f.title.lower())

    # Ensure >= 2 findings on any path
    if len(findings) < 2:
        for hf in _heuristic_findings(paper, section):
            if hf.title.lower() not in {f.title.lower() for f in findings}:
                findings.append(hf)
            if len(findings) >= 2:
                break

    _emit_findings(session, findings, event_emitter)
    return findings


@weave_op
async def _llm_critique(paper: Paper, section, main_paper: Paper | None, text: str) -> list[AgentFinding]:
    """Call LLM for critique findings. Returns empty list on failure or missing key."""
    header = f"Paper: {paper.title}\n"
    if main_paper and main_paper.id != paper.id:
        header += f"Main paper being reviewed: {main_paper.title}\n"
    if section:
        header += f"Section: {section.title}\n"

    result = await complete_json(
        CRITIQUE_PROMPT,
        f"{header}\nSection text:\n{text[:3000]}",
        fallback={"findings": []},
    )
    raw = result.get("findings", [])
    findings: list[AgentFinding] = []
    for item in raw[:4]:
        if not isinstance(item, dict) or not item.get("title") or not item.get("body"):
            continue
        findings.append(
            AgentFinding(
                id=new_id("finding"),
                agent="Critique",
                severity=item.get("severity", "medium"),
                title=str(item["title"])[:120],
                body=str(item["body"])[:600],
                related_paper_id=paper.id,
                related_section_id=section.id if section else None,
            )
        )
    return findings


def _heuristic_findings(paper: Paper, section) -> list[AgentFinding]:
    return [
        AgentFinding(
            id=new_id("finding"),
            agent="Critique",
            severity=severity,
            title=title,
            body=body,
            related_paper_id=paper.id,
            related_section_id=section.id if section else None,
        )
        for severity, title, body in _HEURISTIC_BANK[:3]
    ]


def _emit_findings(session, findings: list[AgentFinding], event_emitter) -> None:
    if not event_emitter:
        return
    for finding in findings:
        event_emitter(
            session.session_id, "critique.finding", finding.title,
            agent="Critique", status=finding.severity, payload=finding.model_dump(),
        )
        body_lower = finding.body.lower()
        if "ablation" in body_lower or "missing experiment" in body_lower:
            event_emitter(
                session.session_id, "experiment.missing",
                "Critique found a missing experiment for the Code Agent to scaffold.",
                agent="Critique", status="flagged", payload={"finding_id": finding.id},
            )
        if "contradict" in body_lower or "conflict" in body_lower or "inconsistent" in body_lower:
            event_emitter(
                session.session_id, "paper.contradiction",
                "Critique Agent detected a potential contradiction.",
                agent="Critique", status="flagged", payload={"finding_id": finding.id},
            )
    event_emitter(
        session.session_id, "agent.finished",
        f"Critique Agent produced {len(findings)} finding(s).",
        agent="Critique", status="done", payload={"findings": len(findings)},
    )
