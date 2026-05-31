from __future__ import annotations

from typing import Any

from app.models import AgentFinding, Paper
from app.services.fixtures import load_lora_fixture
from app.services.sandbox import run_replication_probe


async def run_replication_agent(
    session,
    paper: Paper,
    repo: dict[str, Any] | None = None,
    finding: AgentFinding | None = None,
    event_emitter=None,
) -> dict[str, Any]:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Replication Agent started.", agent="Replication", status="running")

    fixture = load_lora_fixture()["replication"]
    probe = await run_replication_probe()
    scorecard = _build_scorecard(repo, finding)
    result = {
        "status": "dry_run_complete" if probe["returncode"] == 0 else "blocked",
        "repo": repo,
        "claim_under_test": finding.title if finding else fixture["claim_under_test"],
        "expected_metric": fixture["expected_metric"],
        "minimal_reproduction_steps": fixture["minimal_reproduction_steps"],
        "environment": "Local demo dry run. No arbitrary external research repo execution.",
        "risks": fixture["risks"],
        "scorecard": scorecard,
        "blocked_items": _blocked_items(scorecard),
        "next_human_action": _next_human_action(scorecard),
        "logs": [probe["stdout"], probe["stderr"]],
    }
    if event_emitter:
        event_emitter(
            session.session_id,
            "replication.queued",
            "Replication Agent queued a dry-run scorecard.",
            agent="Replication",
            status=result["status"],
            payload=result,
        )
        event_emitter(session.session_id, "agent.finished", "Replication Agent finished.", agent="Replication", status="done")
    return result


def _build_scorecard(repo: dict[str, Any] | None, finding: AgentFinding | None) -> dict[str, Any]:
    has_repo = repo is not None
    confidence = 0.7 if has_repo else 0.42
    if finding and finding.severity == "high":
        confidence -= 0.08
    return {
        "code_available": has_repo,
        "repo_url": repo.get("html_url") if repo else None,
        "install_confidence": "medium" if has_repo else "unknown",
        "data_available": None,
        "compute_feasible": True,
        "metric_plan_ready": True,
        "baseline_parity_ready": False,
        "expected_time": "demo dry run only",
        "confidence": round(confidence, 2),
    }


def _blocked_items(scorecard: dict[str, Any]) -> list[str]:
    blocked = []
    if not scorecard["code_available"]:
        blocked.append("No implementation repository selected.")
    if scorecard["data_available"] is None:
        blocked.append("Dataset availability has not been verified.")
    if not scorecard["baseline_parity_ready"]:
        blocked.append("Matched baseline scripts still need human verification.")
    return blocked


def _next_human_action(scorecard: dict[str, Any]) -> str:
    if not scorecard["code_available"]:
        return "Choose an implementation repository before attempting a real reproduction."
    return "Inspect the selected repo README and confirm dataset, baseline, and hardware settings before any real execution."
