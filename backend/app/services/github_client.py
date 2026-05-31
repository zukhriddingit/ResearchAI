from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import httpx

from app.services.fixtures import load_lora_fixture


async def search_repositories(query: str | Sequence[str], max_results: int = 5) -> list[dict[str, Any]]:
    queries = _normalize_queries(query)
    if not queries:
        return [_fixture_repo("No GitHub search query was available.")]

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return [_fixture_repo("Fixture fallback because GITHUB_TOKEN is not configured.")]

    headers = {"Accept": "application/vnd.github+json"}
    headers["Authorization"] = f"Bearer {token}"
    matches: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=6.0, headers=headers) as client:
        for search_query in queries:
            try:
                matches.extend(await _search_single_query(client, search_query, max_results))
            except Exception:
                continue

    ranked = _rank_repositories(_dedupe_repositories(matches), queries)
    return ranked[:max_results] or [_fixture_repo("GitHub search failed or returned no usable repositories.")]


async def _search_single_query(client: httpx.AsyncClient, query: str, max_results: int) -> list[dict[str, Any]]:
    response = await client.get(
        "https://api.github.com/search/repositories",
        params={
            "q": f"{query} in:name,description,readme",
            "sort": "stars",
            "order": "desc",
            "per_page": max(3, min(max_results, 10)),
        },
    )
    response.raise_for_status()
    repos = response.json().get("items", [])
    return [_normalize_repo(repo, query) for repo in repos]


def _normalize_queries(query: str | Sequence[str]) -> list[str]:
    raw_queries = [query] if isinstance(query, str) else list(query)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_query in raw_queries:
        normalized = " ".join(str(raw_query).split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _dedupe_repositories(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for repo in repos:
        key = repo.get("full_name") or repo.get("html_url") or repo.get("name")
        if not key:
            continue
        existing = deduped.get(key)
        if existing is None or (repo.get("stars") or 0) > (existing.get("stars") or 0):
            deduped[key] = repo
    return list(deduped.values())


def _rank_repositories(repos: list[dict[str, Any]], queries: list[str]) -> list[dict[str, Any]]:
    query_terms = {term.lower() for query in queries for term in query.replace("-", " ").split() if len(term) > 2}

    def score(repo: dict[str, Any]) -> tuple[int, int]:
        haystack = " ".join(
            str(repo.get(key) or "")
            for key in ("name", "full_name", "description", "match_reason")
        ).lower()
        relevance = sum(1 for term in query_terms if term in haystack)
        return relevance, int(repo.get("stars") or 0)

    return sorted(repos, key=score, reverse=True)


def _fixture_repo(reason: str) -> dict[str, Any]:
    repo = dict(load_lora_fixture()["code_repo"])
    repo["match_reason"] = reason
    return repo


def _normalize_repo(repo: dict[str, Any], query: str) -> dict[str, Any]:
    return {
        "name": repo.get("name"),
        "full_name": repo.get("full_name"),
        "html_url": repo.get("html_url"),
        "description": repo.get("description"),
        "stars": repo.get("stargazers_count"),
        "language": repo.get("language"),
        "updated_at": repo.get("updated_at"),
        "match_reason": f"GitHub search match for {query}.",
    }
