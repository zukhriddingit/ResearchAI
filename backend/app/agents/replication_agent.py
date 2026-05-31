from __future__ import annotations

import asyncio
import sys

from app.models import AgentTrigger, Paper
from app.services.fixtures import load_lora_fixture
from app.services.llm import complete_json
from app.services.weave_tracing import op as weave_op


REPLICATION_PROMPT = """\
You are a reproducibility expert. Given a research paper and its repo, produce a replication scorecard.

Return JSON:
{
  "claim_under_test": "...",
  "expected_metric": "...",
  "minimal_reproduction_steps": ["..."],
  "environment": "...",
  "risks": ["..."],
  "scorecard": {
    "code_available": true,
    "data_available": null,
    "compute_feasible": true,
    "expected_time": "...",
    "confidence": 0.0
  },
  "discrepancies": ["..."]
}

`discrepancies` = suspected gaps between reported numbers and what the code would reproduce."""


@weave_op
async def run_replication_agent(
    session, paper: Paper, repo=None, finding=None, event_emitter=None
) -> dict:
    """
    Scaffold a minimal replication plan and scorecard for the paper's key claim.

    Triggers emitted:
        → critique: when discrepancies found (become new findings)
        → evaluation: always (passes baseline numbers forward)
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Replication Agent started.",
                      agent="Replication", status="running")

    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('replication harness ready')",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()

    result = await _build_scorecard(paper, repo, finding)
    result["status"] = "dry_run_complete" if process.returncode == 0 else "blocked"
    result["logs"] = [stdout.decode().strip()]

    triggers: list[dict] = []
    if result.get("discrepancies"):
        triggers.append(AgentTrigger(
            target="critique",
            reason="replication_discrepancy",
            context={"discrepancies": result["discrepancies"], "claim": result["claim_under_test"]},
        ).model_dump())
    triggers.append(AgentTrigger(
        target="evaluation",
        reason="baseline_numbers_ready",
        context={"expected_metric": result["expected_metric"], "paper_id": paper.id},
    ).model_dump())
    result["triggers"] = triggers

    if event_emitter:
        event_emitter(session.session_id, "replication.queued",
                      "Replication Agent created a dry-run scorecard.",
                      agent="Replication", status=result["status"], payload=result)
        event_emitter(session.session_id, "agent.finished", "Replication Agent finished.",
                      agent="Replication", status="done")
    return result


@weave_op
async def _build_scorecard(paper: Paper, repo, finding) -> dict:
    fixture = load_lora_fixture()["replication"]
    claim_text = finding.body if finding else (paper.claims[0].text if paper.claims else fixture["claim_under_test"])
    repo_name = repo.get("full_name", repo.get("name", "unknown")) if repo else "unknown"
    user_msg = (
        f"Paper: {paper.title}\nClaim under test: {claim_text}\n"
        f"Repo: {repo_name}\nKnown risks: {', '.join(fixture['risks'])}"
    )
    fallback = {
        "claim_under_test": fixture["claim_under_test"],
        "expected_metric": fixture["expected_metric"],
        "minimal_reproduction_steps": fixture["minimal_reproduction_steps"],
        "environment": "Local demo dry run.",
        "risks": fixture["risks"],
        "scorecard": {
            "code_available": repo is not None,
            "data_available": None,
            "compute_feasible": True,
            "expected_time": "demo dry run only",
            "confidence": 0.62,
        },
        "discrepancies": [],
    }
    return await complete_json(REPLICATION_PROMPT, user_msg, fallback)
