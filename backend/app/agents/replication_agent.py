from __future__ import annotations

from typing import Any

from app.models import AgentFinding, Paper
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

    probe = await run_replication_probe()
    scorecard = _build_scorecard(repo, finding)
    result = {
        "status": "dry_run_complete" if probe["returncode"] == 0 else "blocked",
        "repo": repo,
        "claim_under_test": finding.title if finding else _claim_under_test(paper),
        "expected_metric": _expected_metric(paper),
        "minimal_reproduction_steps": _minimal_reproduction_steps(paper),
        "environment": "Local dry run. No arbitrary external research repo execution.",
        "risks": _replication_risks(),
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


def _claim_under_test(paper: Paper) -> str:
    return paper.claims[0].text if paper.claims else f"Main result claimed by {paper.title}"


def _expected_metric(paper: Paper) -> str:
    text = f"{paper.title} {paper.abstract or ''}".lower()
    if "classification" in text or "imagenet" in text:
        return "Top-1 accuracy with matched FLOPs/parameters"
    if "object detection" in text or "coco" in text:
        return "COCO AP with matched backbone and schedule"
    if "segmentation" in text:
        return "mIoU with matched backbone and training recipe"
    return "Primary task metric plus compute, memory, and reproducibility notes"


def _minimal_reproduction_steps(paper: Paper) -> list[str]:
    return [
        "Identify the official or closest implementation repository.",
        "Confirm datasets, preprocessing, model scale, and checkpoint availability.",
        f"Select the smallest experiment that tests: {_claim_under_test(paper)}",
        "Record expected metrics, hardware assumptions, blockers, and required human verification.",
    ]


def _replication_risks() -> list[str]:
    return [
        "The implementation may not match the exact paper revision.",
        "Dataset preprocessing and training schedules may be under-specified.",
        "Baselines may require separate repositories or unpublished checkpoints.",
        "Hardware differences can change throughput, memory, and sometimes quality.",
    ]
