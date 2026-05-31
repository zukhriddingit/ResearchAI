from __future__ import annotations

from app.models import AgentFinding, AgentTrigger, CodeEdit, Paper
from app.services.code_generator import ProjectResult, generate_full_project
from app.services.fixtures import load_lora_fixture
from app.services.github_client import search_repositories
from app.services.llm import complete_json, complete_text
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

CODE_GENERATION_PROMPT = """\
You are a research engineer. Given a research paper's method description, generate clean, well-commented Python code that implements the core contribution.

Return JSON:
{
  "filename": "method_name.py",
  "code": "# full Python implementation here",
  "description": "What this implementation covers",
  "dependencies": ["torch", "numpy"],
  "usage_example": "# how to call it",
  "limitations": ["..."]
}

Requirements:
- Use PyTorch unless the paper explicitly uses something else
- Include type hints
- Implement only what is described in the paper — do not hallucinate
- Add a short docstring per function
- Mark places that need tuning with # TODO: paper does not specify ..."""

SUGGESTION_APPLY_PROMPT = """\
You are a senior software engineer applying peer-review feedback to research code.

Given:
- The paper's findings / critique
- The current code context (file paths and snippets)
- The finding to address

Produce a concrete code change.

Return JSON:
{
  "file_path": "path/to/file.py",
  "change_type": "add" | "modify" | "delete",
  "description": "One sentence describing what this change does",
  "original_snippet": "exact code to replace (empty string for pure additions)",
  "new_snippet": "replacement code",
  "rationale": "Why this change addresses the finding"
}

Rules:
- Only change what is needed to address the specific finding
- Do not refactor unrelated code
- If no code change is warranted (e.g. finding is about paper writing), return change_type=add and explain in rationale"""

USER_CHANGE_PROMPT = """\
You are a senior software engineer. Apply the user's requested change to the research codebase.

Return JSON:
{
  "file_path": "path/to/file.py",
  "change_type": "add" | "modify" | "delete",
  "description": "One sentence describing what this change does",
  "original_snippet": "exact code to replace (empty if adding new)",
  "new_snippet": "the new code",
  "rationale": "Why the change fulfils the user's request"
}

Be precise. If the user's request is ambiguous, make a conservative, reasonable interpretation."""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@weave_op
async def run_code_agent(
    session, paper: Paper, section=None, finding=None, event_emitter=None
) -> dict:
    """
    Find or generate the implementation repo for a paper, then contextualize it
    against the paper's claims.

    Triggers emitted:
        → replication: repo found (hands off entrypoint)
        → adversarial: repo found (code is the attack surface)
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started",
                      "Code Agent searching for implementation.",
                      agent="Code", status="running")

    query = f"{paper.title} {paper.arxiv_id or ''}".strip()
    repos = await search_repositories(query, max_results=3)
    repo = repos[0] if repos else load_lora_fixture()["code_repo"]

    repo_is_real = bool(repos)
    analysis = await _analyze_repo(paper, repo, finding)

    # Always offer generated code (both when repo found and when not)
    if event_emitter:
        event_emitter(session.session_id, "code.generating",
                      "Generating full project — use POST /code/generate for the ZIP.",
                      agent="Code", status="running")
    # We don't run the full generator here (it's slow); surface it via /code/generate.
    # Just record that generation is available.
    generated_code: dict = {
        "available": True,
        "hint": "POST /api/sessions/{session_id}/code/generate to get the full ZIP",
    }

    triggers: list[dict] = [
        AgentTrigger(
            target="replication",
            reason="repo_found",
            context={"repo": repo,
                     "entrypoint": analysis["handoff_to_replication"]["entrypoint_guess"]},
        ).model_dump(),
        AgentTrigger(
            target="adversarial",
            reason="code_available",
            context={"repo": repo, "code_gaps": analysis.get("code_gaps", [])},
        ).model_dump(),
    ]

    result = {
        "repo": repo,
        "repo_is_real": repo_is_real,
        **analysis,
        "generated_code": generated_code,
        "triggers": triggers,
    }

    if event_emitter:
        event_emitter(session.session_id, "repo.ready",
                      f"Code Agent: {repo.get('full_name', repo.get('name', '?'))}",
                      agent="Code", status="done",
                      payload={"repo": repo, "key_files": analysis["key_files"],
                               "generated": bool(generated_code)})
    return result


# ---------------------------------------------------------------------------
# Repo analysis
# ---------------------------------------------------------------------------

@weave_op
async def _analyze_repo(paper: Paper, repo: dict, finding=None) -> dict:
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


# ---------------------------------------------------------------------------
# Code generation from paper — full multi-file project
# ---------------------------------------------------------------------------

@weave_op
async def _generate_code_from_paper(
    paper: Paper,
    repo: dict,
    section=None,
    event_emitter=None,
    session=None,
) -> dict:
    """
    Generate a complete, multi-file Python project from the paper.
    Returns a dict with project_name, description, file_count, file_list,
    total_lines, and zip_bytes (raw bytes of the ZIP archive).
    """
    result: ProjectResult = await generate_full_project(
        paper=paper,
        repo=repo,
        equations=paper.equations or None,
        event_emitter=event_emitter,
        session=session,
    )
    return {
        **result.to_json_safe(),
        "zip_bytes": result.zip_bytes,   # raw bytes — caller stores in session store
        "files_preview": {               # first 800 chars per file for the API response
            path: content[:800]
            for path, content in list(result.files.items())[:6]
        },
    }


# ---------------------------------------------------------------------------
# Apply findings/critique to code
# ---------------------------------------------------------------------------

@weave_op
async def apply_suggestions(
    paper: Paper,
    findings: list[AgentFinding],
    repo: dict,
    event_emitter=None,
    session=None,
) -> list[CodeEdit]:
    """
    For each agent finding, generate a concrete CodeEdit suggesting how to address it.
    Returns a list of CodeEdit objects (one per finding, where actionable).
    """
    edits: list[CodeEdit] = []

    for finding in findings:
        if event_emitter and session:
            event_emitter(session.session_id, "code.suggestion",
                          f"Generating code suggestion for: {finding.title[:60]}",
                          agent="Code", status="running")

        edit = await _suggestion_for_finding(paper, finding, repo)
        if edit:
            edits.append(edit)

    if event_emitter and session:
        event_emitter(session.session_id, "code.suggestions_ready",
                      f"Code Agent produced {len(edits)} code suggestions.",
                      agent="Code", status="done",
                      payload={"count": len(edits)})
    return edits


@weave_op
async def _suggestion_for_finding(paper: Paper, finding: AgentFinding, repo: dict) -> CodeEdit | None:
    repo_name = repo.get("full_name", repo.get("name", "unknown"))
    user_msg = (
        f"Paper: {paper.title}\n"
        f"Repo: {repo_name}\n\n"
        f"Finding [{finding.severity.upper()}]: {finding.title}\n"
        f"{finding.body}\n\n"
        f"Suggest the minimal code change to address this finding."
    )
    fallback = {
        "file_path": "experiment.py",
        "change_type": "modify",
        "description": f"Address: {finding.title[:80]}",
        "original_snippet": "",
        "new_snippet": f"# TODO: address finding — {finding.title}\n",
        "rationale": finding.body[:300],
    }
    result = await complete_json(SUGGESTION_APPLY_PROMPT, user_msg, fallback)
    try:
        return CodeEdit(
            file_path=str(result.get("file_path", fallback["file_path"])),
            change_type=result.get("change_type", "modify"),  # type: ignore[arg-type]
            description=str(result.get("description", fallback["description"]))[:200],
            original_snippet=str(result.get("original_snippet", "")),
            new_snippet=str(result.get("new_snippet", fallback["new_snippet"])),
            rationale=str(result.get("rationale", fallback["rationale"]))[:400],
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Apply a user-requested change
# ---------------------------------------------------------------------------

@weave_op
async def apply_user_change(
    paper: Paper,
    user_message: str,
    repo: dict,
    target_files: list[str] | None = None,
    event_emitter=None,
    session=None,
) -> CodeEdit:
    """
    Translate a free-form user instruction into a concrete CodeEdit.
    Example user_message: "Add gradient checkpointing to the training loop"
    """
    if event_emitter and session:
        event_emitter(session.session_id, "code.user_change",
                      f"Applying user change: {user_message[:80]}",
                      agent="Code", status="running")

    repo_name = repo.get("full_name", repo.get("name", "unknown"))
    files_ctx = f"Target files: {', '.join(target_files)}" if target_files else ""
    user_msg = (
        f"Paper: {paper.title}\n"
        f"Repo: {repo_name}\n"
        f"{files_ctx}\n\n"
        f"User request: {user_message}"
    )
    fallback = {
        "file_path": "train.py",
        "change_type": "modify",
        "description": f"User-requested: {user_message[:80]}",
        "original_snippet": "",
        "new_snippet": f"# User requested: {user_message}\n# TODO: implement\n",
        "rationale": f"Applies user instruction: {user_message[:300]}",
    }
    result = await complete_json(USER_CHANGE_PROMPT, user_msg, fallback)
    edit = CodeEdit(
        file_path=str(result.get("file_path", fallback["file_path"])),
        change_type=result.get("change_type", "modify"),  # type: ignore[arg-type]
        description=str(result.get("description", fallback["description"]))[:200],
        original_snippet=str(result.get("original_snippet", "")),
        new_snippet=str(result.get("new_snippet", fallback["new_snippet"])),
        rationale=str(result.get("rationale", fallback["rationale"]))[:400],
    )

    if event_emitter and session:
        event_emitter(session.session_id, "code.user_change_ready",
                      f"Code edit ready: {edit.description}",
                      agent="Code", status="done",
                      payload=edit.model_dump())
    return edit
