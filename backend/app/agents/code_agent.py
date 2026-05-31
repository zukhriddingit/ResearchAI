from __future__ import annotations

from app.models import AgentTrigger, Paper
from app.services.fixtures import load_lora_fixture
from app.services.github_client import search_repositories
from app.services.llm import complete_json
from app.services.weave_tracing import op as weave_op


CODE_ANALYSIS_PROMPT = """\
You are a research code analyst. Given a paper and its GitHub repo, explain the implementation relative to the paper's specific claims.

Return JSON:
{
  "key_files": [{"path": "...", "why_relevant": "..."}],
  "paper_claim_connection": "...",
  "implementation_risks": ["..."],
  "handoff_to_replication": {
    "entrypoint_guess": "...",
    "setup_guess": "...",
    "minimal_run_plan": ["..."]
  },
  "code_gaps": ["..."]
}

`code_gaps` = discrepancies between what the paper claims and what the code likely does."""


@weave_op
async def run_code_agent(
    session, paper: Paper, section=None, finding=None, event_emitter=None
) -> dict:
    """
    Find the implementation repo for a paper and contextualize it against claims.

    Triggers emitted:
        → replication: repo found (hands off entrypoint)
        → adversarial: repo found (code is the attack surface)
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Code Agent searching for implementation.",
                      agent="Code", status="running")

    query = f"{paper.title} {paper.arxiv_id or ''}".strip()
    repos = await search_repositories(query, max_results=3)
    repo = repos[0] if repos else load_lora_fixture()["code_repo"]

    analysis = await _analyze_repo(paper, repo, finding)

    triggers: list[dict] = [
        AgentTrigger(
            target="replication",
            reason="repo_found",
            context={"repo": repo, "entrypoint": analysis["handoff_to_replication"]["entrypoint_guess"]},
        ).model_dump(),
        AgentTrigger(
            target="adversarial",
            reason="code_available",
            context={"repo": repo, "code_gaps": analysis.get("code_gaps", [])},
        ).model_dump(),
    ]

    result = {"repo": repo, **analysis, "triggers": triggers}

    if event_emitter:
        event_emitter(session.session_id, "repo.ready",
                      f"Code Agent found: {repo.get('full_name', repo.get('name', '?'))}",
                      agent="Code", status="done",
                      payload={"repo": repo, "key_files": analysis["key_files"]})
    return result


@weave_op
async def _analyze_repo(paper: Paper, repo: dict, finding=None) -> dict:
    """LLM analysis of repo vs paper claims."""
    claims_text = " | ".join(c.text for c in paper.claims[:4]) if paper.claims else "None extracted."
    finding_ctx = f"\nFinding to scaffold: {finding.title} — {finding.body}" if finding else ""
    user_msg = (
        f"Paper: {paper.title}\nClaims: {claims_text}\n"
        f"Repo: {repo.get('full_name', repo.get('name', ''))}\n"
        f"Description: {repo.get('description', '')}{finding_ctx}"
    )
    fallback = {
        "key_files": [
            {"path": "loralib/layers.py", "why_relevant": "Core LoRA layer implementation."},
            {"path": "examples/", "why_relevant": "Reproduction entry points."},
        ],
        "paper_claim_connection": f"The repo implements {paper.title}'s core method.",
        "implementation_risks": [
            "Benchmark scripts may not exactly match the paper.",
            "Baseline implementations may differ from what the paper reports.",
        ],
        "handoff_to_replication": {
            "entrypoint_guess": "examples/",
            "setup_guess": "pip install -r requirements.txt && pip install -e .",
            "minimal_run_plan": [
                "Run the smallest published task configuration.",
                "Record metrics and compare to paper Table 1.",
            ],
        },
        "code_gaps": [],
    }
    return await complete_json(CODE_ANALYSIS_PROMPT, user_msg, fallback)
