from __future__ import annotations

from app.models import AgentFinding, Paper, new_id
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json, reasoning_model


CRITIQUE_PROMPT = """You are the Critique Agent for DeepPaper.
Find weak baselines, missing ablations, leakage risks, significance gaps, overclaims, compute gaps, and reproducibility issues.
Every finding must be contextual to the main paper and actionable for a replication/code agent."""


async def run_critique_agent(session, paper: Paper, section=None, main_paper: Paper | None = None, event_emitter=None) -> list[AgentFinding]:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Critique Agent started.", agent="Critique", status="running")

    fixture_findings = load_lora_fixture()["critique_findings"]
    findings = [AgentFinding.model_validate(item) for item in fixture_findings]

    if section:
        findings = [finding for finding in findings if finding.related_section_id == section.id] or findings[:1]

    fallback = {"findings": [finding.model_dump() for finding in findings]}
    llm_result = await complete_json(
        CRITIQUE_PROMPT,
        (
            f"Main paper: {(main_paper or paper).title}\n"
            f"Paper abstract: {paper.abstract or ''}\n"
            f"Section title: {section.title if section else 'Full paper'}\n"
            f"Section text: {(section.text if section else ' '.join(s.text for s in paper.sections[:3]))[:3500]}\n"
            "Return JSON: {\"findings\": [{\"severity\":\"low|medium|high\", "
            "\"title\":\"...\", \"body\":\"...\", \"related_section_id\":\"...\"}]}"
        ),
        fallback,
        model=reasoning_model(),
        temperature=0.15,
        max_tokens=900,
    )
    findings = _parse_findings(llm_result, fallback, paper.id, section.id if section else None, "Critique")

    for finding in findings:
        if event_emitter:
            event_emitter(
                session.session_id,
                "critique.finding",
                finding.title,
                agent="Critique",
                status=finding.severity,
                payload=finding.model_dump(),
            )
            if "missing experiment" in finding.body.lower() or "ablation" in finding.body.lower():
                event_emitter(
                    session.session_id,
                    "experiment.missing",
                    "Critique found an experiment for the Code Agent to scaffold.",
                    agent="Critique",
                    status="flagged",
                    payload={"finding_id": finding.id},
                )

    if event_emitter:
        event_emitter(
            session.session_id,
            "agent.finished",
            "Critique Agent produced findings.",
            agent="Critique",
            status="done",
            payload={"findings": len(findings)},
        )
    return findings


def _parse_findings(result: dict, fallback: dict, paper_id: str, section_id: str | None, agent: str) -> list[AgentFinding]:
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
                agent=agent,
                severity=severity,
                title=str(item.get("title") or "Research critique"),
                body=str(item.get("body") or "This claim needs additional validation."),
                related_paper_id=str(item.get("related_paper_id") or paper_id),
                related_section_id=str(item.get("related_section_id") or section_id) if (item.get("related_section_id") or section_id) else None,
                related_claim_id=str(item.get("related_claim_id")) if item.get("related_claim_id") else None,
            )
        )
    return findings or [AgentFinding.model_validate(item) for item in fallback["findings"]]
