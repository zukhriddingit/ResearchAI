from __future__ import annotations

from app.models import AgentFinding, Paper
from app.services.fixtures import load_lora_fixture


CRITIQUE_PROMPT = (
    "Find weak baselines, missing ablations, leakage risks, significance gaps, overclaims, compute gaps, and reproducibility issues."
)


async def run_critique_agent(session, paper: Paper, section=None, main_paper: Paper | None = None, event_emitter=None) -> list[AgentFinding]:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Critique Agent started.", agent="Critique", status="running")

    fixture_findings = load_lora_fixture()["critique_findings"]
    findings = [AgentFinding.model_validate(item) for item in fixture_findings]

    if section:
        findings = [finding for finding in findings if finding.related_section_id == section.id] or findings[:1]

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

