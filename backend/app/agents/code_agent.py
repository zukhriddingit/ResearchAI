from __future__ import annotations

from typing import Any

from app.models import AgentFinding, Paper
from app.services.github_client import search_repositories


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
    handoff = _build_replication_handoff(paper, repo, finding)
    result = {
        "repo": repo,
        "candidate_repos": repos,
        "search_queries": queries,
        "key_files": _infer_key_files(repo, paper),
        "paper_claim_connection": _claim_connection(paper, finding),
        "implementation_risks": _implementation_risks(finding),
        "handoff_to_replication": handoff,
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
