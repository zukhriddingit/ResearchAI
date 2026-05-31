from __future__ import annotations

from app.models import AgentFinding, AgentTrigger, Paper, new_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json, complete_with_vision
from app.services.weave_tracing import op as weave_op


CRITIQUE_PROMPT = """\
You are a rigorous scientific peer reviewer. Analyze the research paper section and return critique findings.

Critique categories: weak/missing baselines, missing ablations, dataset leakage, statistical significance gaps,
overclaimed generalization, train/test contamination, unclear compute budget, cherry-picked benchmarks, reproducibility gaps.

Return JSON (2-4 findings):
{
  "findings": [
    {
      "severity": "low" | "medium" | "high",
      "title": "Short finding title (under 80 chars)",
      "body": "Specific explanation with text evidence.",
      "implies_missing_experiment": true | false,
      "implies_contradiction": false
    }
  ]
}"""

VISION_TABLE_PROMPT = """\
You are a critical reviewer examining a results table from a research paper.

Look for:
- Missing baseline rows (strong known competitors not included)
- Suspicious formatting: bold numbers that are marginal wins, missing standard deviations
- Y-axis or scale manipulation if the table shows a chart
- Cherry-picked metrics (best metric shown, others omitted)
- Missing ablation rows

Return JSON:
{
  "findings": [
    {"severity": "low"|"medium"|"high", "title": "...", "body": "..."}
  ]
}

Be specific. Reference the actual column headers or row names you can see."""

_HEURISTIC_BANK = [
    ("medium", "Baseline comparison may be incomplete",
     "Claims of improvement should be validated against the strongest contemporaneous baselines."),
    ("medium", "Ablation coverage unclear",
     "Without systematic ablations, it is difficult to attribute performance gains to specific design choices."),
    ("low", "Statistical significance not reported",
     "Results lack variance estimates or confidence intervals across multiple random seeds."),
    ("medium", "Generalization to other domains not demonstrated",
     "Experiments on a narrow task distribution may not generalize."),
    ("low", "Compute budget not clearly specified",
     "Reproducibility requires hardware, training time, and hyperparameter search cost."),
    ("medium", "Reproducibility details incomplete",
     "Full replication requires dataset preprocessing, optimizer schedules, and random seeds."),
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
    Generate critique findings — text-based and vision-based (results tables).

    Weave trace:
        run_critique_agent
          ├── _llm_critique          → complete_json → LLM call
          └── _vision_table_critique → complete_with_vision → vision LLM call

    Triggers emitted:
        → code: missing experiment findings
        → adversarial: high-severity findings (most vulnerable claims)
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Critique Agent started.",
                      agent="Critique", status="running")

    fixture_raw = load_lora_fixture()["critique_findings"]
    fixture_findings = [AgentFinding.model_validate(item) for item in fixture_raw]

    if section:
        section_findings = [f for f in fixture_findings if f.related_section_id == section.id]
        findings: list[AgentFinding] = section_findings if section_findings else fixture_findings
    else:
        findings = list(fixture_findings)

    # LLM text critique
    section_text = section.text if section else (
        paper.sections[1].text if len(paper.sections) > 1 else
        paper.sections[0].text if paper.sections else ""
    )
    if section_text:
        extra = await _llm_critique(paper, section, main_paper, section_text)
        existing = {f.title.lower() for f in findings}
        for f in extra:
            if f.title.lower() not in existing:
                findings.append(f)
                existing.add(f.title.lower())

    # Vision critique: analyze any result tables in this section
    if section and section.tables:
        vision_findings = await _vision_table_critique(paper, section)
        existing = {f.title.lower() for f in findings}
        for f in vision_findings:
            if f.title.lower() not in existing:
                findings.append(f)

    if len(findings) < 2:
        for hf in _heuristic_findings(paper, section):
            if hf.title.lower() not in {f.title.lower() for f in findings}:
                findings.append(hf)
            if len(findings) >= 2:
                break

    # Build triggers
    triggers: list[dict] = []
    for f in findings:
        body_lower = f.body.lower()
        if "ablation" in body_lower or "missing experiment" in body_lower:
            triggers.append(AgentTrigger(
                target="code", reason="missing_experiment",
                context={"finding_id": f.id, "title": f.title},
            ).model_dump())
        if f.severity == "high":
            triggers.append(AgentTrigger(
                target="adversarial", reason="vulnerable_claim",
                context={"finding_id": f.id, "title": f.title},
            ).model_dump())

    _emit_findings(session, findings, event_emitter, triggers)
    return findings


@weave_op
async def _llm_critique(paper: Paper, section, main_paper: Paper | None, text: str) -> list[AgentFinding]:
    header = f"Paper: {paper.title}\n"
    if main_paper and main_paper.id != paper.id:
        header += f"Main paper context: {main_paper.title}\n"
    if section:
        header += f"Section: {section.title}\n"

    result = await complete_json(CRITIQUE_PROMPT, f"{header}\nSection text:\n{text[:3000]}", {"findings": []})
    raw = result.get("findings", [])
    findings: list[AgentFinding] = []
    for item in raw[:4]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        findings.append(AgentFinding(
            id=new_id("finding"), agent="Critique",
            severity=item.get("severity", "medium"),
            title=str(item["title"])[:120], body=str(item.get("body", ""))[:600],
            related_paper_id=paper.id,
            related_section_id=section.id if section else None,
        ))
    return findings


@weave_op
async def _vision_table_critique(paper: Paper, section) -> list[AgentFinding]:
    """
    Pass result table images to the vision LLM and extract critique findings.
    This is the 'y-axis trick' detector: catches cherry-picked ranges, missing rows, etc.
    """
    images = [t.image_b64 for t in section.tables if t.image_b64]
    if not images:
        return []

    table_context = "; ".join(
        t.caption or f"Table on page {i}" for i, t in enumerate(section.tables) if t.image_b64
    )
    user_msg = (
        f"Paper: {paper.title}\nSection: {section.title}\n"
        f"Tables shown: {table_context}\n\n"
        "Analyze each table image for statistical or presentation issues."
    )
    text = await complete_with_vision(
        VISION_TABLE_PROMPT,
        user_msg,
        images[:3],
        fallback='{"findings": []}',
    )
    # Strip fences
    import re
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())

    import json
    try:
        raw = json.loads(text).get("findings", [])
    except Exception:
        return []

    findings: list[AgentFinding] = []
    for item in raw[:3]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        findings.append(AgentFinding(
            id=new_id("finding"), agent="Critique",
            severity=item.get("severity", "medium"),
            title=f"[Vision] {item['title']}"[:120],
            body=str(item.get("body", ""))[:600],
            related_paper_id=paper.id,
            related_section_id=section.id,
        ))
    return findings


def _heuristic_findings(paper: Paper, section) -> list[AgentFinding]:
    return [
        AgentFinding(
            id=new_id("finding"), agent="Critique", severity=severity,
            title=title, body=body, related_paper_id=paper.id,
            related_section_id=section.id if section else None,
        )
        for severity, title, body in _HEURISTIC_BANK[:3]
    ]


def _emit_findings(session, findings: list[AgentFinding], event_emitter, triggers: list[dict]) -> None:
    if not event_emitter:
        return
    for finding in findings:
        event_emitter(session.session_id, "critique.finding", finding.title,
                      agent="Critique", status=finding.severity, payload=finding.model_dump())
        body_lower = finding.body.lower()
        if "ablation" in body_lower or "missing experiment" in body_lower:
            event_emitter(session.session_id, "experiment.missing",
                          "Critique found a missing experiment for the Code Agent.",
                          agent="Critique", status="flagged", payload={"finding_id": finding.id})
        if "contradict" in body_lower or "conflict" in body_lower:
            event_emitter(session.session_id, "paper.contradiction",
                          "Critique Agent detected a potential contradiction.",
                          agent="Critique", status="flagged", payload={"finding_id": finding.id})
    event_emitter(session.session_id, "agent.finished",
                  f"Critique Agent produced {len(findings)} finding(s).",
                  agent="Critique", status="done",
                  payload={"findings": len(findings), "triggers": triggers})
