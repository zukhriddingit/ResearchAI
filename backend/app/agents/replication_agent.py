from __future__ import annotations

import asyncio
import sys

from app.models import Paper
from app.services.fixtures import load_lora_fixture


async def run_replication_agent(session, paper: Paper, repo=None, finding=None, event_emitter=None) -> dict:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Replication Agent started.", agent="Replication", status="running")

    fixture = load_lora_fixture()["replication"]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "print('replication harness ready')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    result = {
        "status": "dry_run_complete" if process.returncode == 0 else "blocked",
        "claim_under_test": fixture["claim_under_test"],
        "expected_metric": fixture["expected_metric"],
        "minimal_reproduction_steps": fixture["minimal_reproduction_steps"],
        "environment": "Local demo dry run. No arbitrary research repo execution.",
        "risks": fixture["risks"],
        "scorecard": {
            "code_available": repo is not None,
            "data_available": None,
            "compute_feasible": True,
            "expected_time": "demo dry run only",
            "confidence": 0.62,
        },
        "logs": [stdout.decode().strip(), stderr.decode().strip()],
    }
    if event_emitter:
        event_emitter(session.session_id, "replication.queued", "Replication Agent created a dry-run scorecard.", agent="Replication", status=result["status"], payload=result)
        event_emitter(session.session_id, "agent.finished", "Replication Agent finished.", agent="Replication", status="done")
    return result
