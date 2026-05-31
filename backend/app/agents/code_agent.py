from __future__ import annotations

from typing import Any

from app.models import AgentFinding, AgentTrigger, CodeEdit, Paper
from app.services.github_client import search_repositories
from app.services.llm import complete_json, reasoning_model


CODE_GENERATION_PROMPT = """You are a research engineer. Given a paper's method description, generate clean Python code that sketches the core contribution.
Return JSON with filename, code, description, dependencies, usage_example, and limitations.
Use PyTorch when appropriate. Mark underspecified parts with TODO comments."""

SUGGESTION_APPLY_PROMPT = """You are a senior software engineer applying research-review feedback to code.
Return JSON with file_path, change_type, description, original_snippet, new_snippet, and rationale."""

USER_CHANGE_PROMPT = """You are a senior software engineer. Convert the user's requested change into a concrete CodeEdit.
Return JSON with file_path, change_type, description, original_snippet, new_snippet, and rationale."""


async def run_code_agent(
    session,
    paper: Paper,
    section=None,
    finding: AgentFinding | None = None,
    event_emitter=None,
) -> dict[str, Any]:
    queries = _build_search_queries(paper, finding)
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Code Agent started.", agent="Code", status="running")
        event_emitter(
            session.session_id,
            "code.search.started",
            "Code Agent searching for implementation repos.",
            agent="Code",
            status="running",
            payload={"queries": queries, "finding_id": finding.id if finding else None},
        )

    repos = await search_repositories(queries, max_results=5)
    repo = _select_repo(repos, paper)
    repo_is_real = _repo_is_real(repo)
    handoff = _build_replication_handoff(paper, repo, finding)
    generated_code = {}
    if not repo_is_real:
        if event_emitter:
            event_emitter(
                session.session_id,
                "code.generating",
                "No verified public repository found, so Code Agent is generating a method skeleton.",
                agent="Code",
                status="running",
            )
        generated_code = await _generate_code_from_paper(paper, section)
    triggers = [
        AgentTrigger(target="replication", reason="repo_found", context={"repo": repo, "entrypoint": handoff["entrypoint_guess"]}).model_dump(),
        AgentTrigger(target="adversarial", reason="code_available", context={"repo": repo}).model_dump(),
    ]
    result = {
        "repo": repo,
        "repo_is_real": repo_is_real,
        "candidate_repos": repos,
        "search_queries": queries,
        "key_files": _infer_key_files(repo, paper),
        "paper_claim_connection": _claim_connection(paper, finding),
        "implementation_risks": _implementation_risks(finding),
        "handoff_to_replication": handoff,
        "generated_code": generated_code,
        "code_gaps": _code_gaps(repo, paper, repo_is_real),
        "triggers": triggers,
    }
    if event_emitter:
        event_emitter(
            session.session_id,
            "repo.ready",
            "Code Agent found a candidate implementation repo and handed it to Replication.",
            agent="Code",
            status="done",
            payload=result,
        )
        event_emitter(
            session.session_id,
            "agent.finished",
            "Code Agent finished.",
            agent="Code",
            status="done",
            payload={"repo": repo.get("full_name"), "handoff": handoff["claim_under_test"]},
        )
    return result


def _repo_is_real(repo: dict[str, Any]) -> bool:
    full_name = str(repo.get("full_name") or "")
    return bool(repo.get("html_url")) and not full_name.startswith("local/")


def _build_search_queries(paper: Paper, finding: AgentFinding | None) -> list[str]:
    queries = [
        f"{paper.title} {paper.arxiv_id or ''}",
        paper.title,
    ]
    if paper.arxiv_id:
        queries.append(paper.arxiv_id)

    method_terms = _method_terms(paper)
    queries.extend(method_terms)
    if paper.authors and method_terms:
        last_name = paper.authors[0].split()[-1]
        queries.append(f"{last_name} {method_terms[0]}")
    if finding:
        queries.append(f"{method_terms[0] if method_terms else paper.title} {finding.title}")
    return _dedupe([query for query in queries if query.strip()])


def _method_terms(paper: Paper) -> list[str]:
    text = " ".join(
        [
            paper.title,
            paper.abstract or "",
            " ".join(claim.text for claim in paper.claims),
        ]
    ).lower()
    terms: list[str] = []
    if "lora" in text or "low-rank adaptation" in text:
        terms.extend(["LoRA", "Low-Rank Adaptation", "loralib"])
    if "adapter" in text:
        terms.append("adapter tuning")
    if "prefix" in text:
        terms.append("prefix tuning")
    return _dedupe(terms) or [paper.title]


def _select_repo(repos: list[dict[str, Any]], paper: Paper) -> dict[str, Any]:
    if not repos:
        raise ValueError("Code Agent received no repository candidates.")
    title_terms = {term.lower() for term in paper.title.replace(":", " ").split() if len(term) > 2}

    def score(repo: dict[str, Any]) -> tuple[int, int]:
        haystack = " ".join(str(repo.get(key) or "") for key in ("name", "full_name", "description")).lower()
        relevance = sum(1 for term in title_terms if term in haystack)
        if paper.arxiv_id and paper.arxiv_id in str(repo.get("match_reason") or ""):
            relevance += 2
        return relevance, int(repo.get("stars") or 0)

    return sorted(repos, key=score, reverse=True)[0]


def _infer_key_files(repo: dict[str, Any], paper: Paper) -> list[dict[str, str]]:
    haystack = f"{repo.get('full_name', '')} {repo.get('description', '')} {paper.title}".lower()
    if "lora" in haystack:
        return [
            {"path": "loralib/layers.py", "why_relevant": "Contains LoRA layer wrappers and merge behavior."},
            {"path": "examples/NLG", "why_relevant": "Likely entrypoint for a small language generation reproduction."},
            {"path": "README.md", "why_relevant": "Expected setup and benchmark instructions for the replication dry run."},
        ]
    return [
        {"path": "README.md", "why_relevant": "Setup and usage instructions for a safe replication plan."},
        {"path": "examples/", "why_relevant": "Likely location for minimal paper-aligned experiments."},
        {"path": "requirements.txt", "why_relevant": "Dependency surface for replication feasibility."},
    ]


def _claim_connection(paper: Paper, finding: AgentFinding | None) -> str:
    if finding:
        return (
            f"The repository should be inspected against '{finding.title}' from the main paper critique, "
            "so Replication can queue a focused dry run rather than a generic code search."
        )
    if paper.claims:
        claim = paper.claims[0].text
        return f"The repository is connected to the main paper claim: {claim}"
    return "The repository is connected to the main paper implementation and should be used for a dry-run replication scorecard."


def _implementation_risks(finding: AgentFinding | None) -> list[str]:
    risks = [
        "Benchmark scripts may not match the exact paper settings.",
        "Dataset preprocessing and hardware details can change reported quality and throughput.",
    ]
    if finding:
        risks.append(f"The critique finding '{finding.title}' may require extra baselines beyond the selected repo.")
    return risks


def _code_gaps(repo: dict[str, Any], paper: Paper, repo_is_real: bool) -> list[str]:
    if not repo_is_real:
        return ["No verified public implementation repository was selected; generated code is only a scaffold."]
    description = f"{repo.get('description', '')} {repo.get('match_reason', '')}".lower()
    gaps = []
    if paper.arxiv_id and paper.arxiv_id not in description:
        gaps.append("Repository match does not explicitly mention the paper arXiv ID.")
    if not repo.get("updated_at"):
        gaps.append("Repository freshness could not be verified from GitHub metadata.")
    return gaps


async def _generate_code_from_paper(paper: Paper, section=None) -> dict[str, Any]:
    method_text = section.text[:3000] if section else ""
    if not method_text:
        method_text = next(
            (paper_section.text[:3000] for paper_section in paper.sections if paper_section.type in {"method", "methodology", "approach"}),
            paper.sections[0].text[:2000] if paper.sections else paper.abstract or "",
        )
    fallback = {
        "filename": f"{_safe_filename(paper.title)}_impl.py",
        "code": f'"""\nGenerated skeleton for: {paper.title}\nFill TODOs from the paper before running.\n"""\n\n# TODO: implement the method described in the paper.\n',
        "description": f"Skeleton implementation of {paper.title}",
        "dependencies": ["torch", "numpy"],
        "usage_example": "# Instantiate the module and pass paper-specific inputs.",
        "limitations": ["Skeleton only; needs human validation against the paper."],
    }
    return await complete_json(
        CODE_GENERATION_PROMPT,
        f"Paper title: {paper.title}\nClaims: {[claim.text for claim in paper.claims[:4]]}\nMethod text:\n{method_text}",
        fallback,
        model=reasoning_model(),
        temperature=0.15,
        max_tokens=1200,
    )


async def apply_suggestions(
    paper: Paper,
    findings: list[AgentFinding],
    repo: dict[str, Any],
    event_emitter=None,
    session=None,
) -> list[CodeEdit]:
    edits: list[CodeEdit] = []
    for finding in findings:
        edit = await _suggestion_for_finding(paper, finding, repo)
        if edit:
            edits.append(edit)
    if event_emitter and session:
        event_emitter(
            session.session_id,
            "code.suggestions_ready",
            f"Code Agent produced {len(edits)} code suggestion(s).",
            agent="Code",
            status="done",
            payload={"count": len(edits)},
        )
    return edits


async def _suggestion_for_finding(paper: Paper, finding: AgentFinding, repo: dict[str, Any]) -> CodeEdit | None:
    fallback = {
        "file_path": "experiment.py",
        "change_type": "modify",
        "description": f"Address: {finding.title[:80]}",
        "original_snippet": "",
        "new_snippet": f"# TODO: address finding - {finding.title}\n",
        "rationale": finding.body[:300],
    }
    result = await complete_json(
        SUGGESTION_APPLY_PROMPT,
        f"Paper: {paper.title}\nRepo: {repo.get('full_name') or repo.get('name')}\nFinding: {finding.title}\n{finding.body}",
        fallback,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=900,
    )
    return _code_edit_from_result(result, fallback)


async def apply_user_change(
    paper: Paper,
    user_message: str,
    repo: dict[str, Any],
    target_files: list[str] | None = None,
    event_emitter=None,
    session=None,
) -> CodeEdit:
    fallback = {
        "file_path": target_files[0] if target_files else "train.py",
        "change_type": "modify",
        "description": f"User-requested: {user_message[:80]}",
        "original_snippet": "",
        "new_snippet": f"# User requested: {user_message}\n# TODO: implement\n",
        "rationale": f"Applies user instruction: {user_message[:300]}",
    }
    result = await complete_json(
        USER_CHANGE_PROMPT,
        f"Paper: {paper.title}\nRepo: {repo.get('full_name') or repo.get('name')}\nTarget files: {target_files or []}\nUser request: {user_message}",
        fallback,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=900,
    )
    edit = _code_edit_from_result(result, fallback) or CodeEdit(**fallback)
    if event_emitter and session:
        event_emitter(session.session_id, "code.user_change_ready", f"Code edit ready: {edit.description}", agent="Code", status="done", payload=edit.model_dump())
    return edit


def _code_edit_from_result(result: dict[str, Any], fallback: dict[str, Any]) -> CodeEdit | None:
    try:
        return CodeEdit(
            file_path=str(result.get("file_path") or fallback["file_path"]),
            change_type=result.get("change_type") if result.get("change_type") in {"add", "modify", "delete"} else fallback["change_type"],
            description=str(result.get("description") or fallback["description"])[:200],
            original_snippet=str(result.get("original_snippet") or ""),
            new_snippet=str(result.get("new_snippet") or fallback["new_snippet"]),
            rationale=str(result.get("rationale") or fallback["rationale"])[:500],
        )
    except Exception:
        return None


def _build_replication_handoff(
    paper: Paper,
    repo: dict[str, Any],
    finding: AgentFinding | None,
) -> dict[str, Any]:
    claim = finding.title if finding else (paper.claims[0].text if paper.claims else paper.title)
    return {
        "repo_full_name": repo.get("full_name"),
        "claim_under_test": claim,
        "entrypoint_guess": "examples/NLG" if "lora" in str(repo.get("full_name", "")).lower() else "examples/",
        "setup_guess": "pip install -r requirements.txt && pip install -e .",
        "minimal_run_plan": [
            "Inspect README and example scripts without executing arbitrary repo code.",
            "Select the smallest paper-aligned task configuration.",
            "Record expected metrics: quality, trainable parameters, memory, and throughput.",
            "Queue a dry-run scorecard with blockers and required human verification.",
        ],
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _safe_filename(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:40] or "paper_method"
