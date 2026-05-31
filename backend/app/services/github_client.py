from __future__ import annotations

import os
from typing import Any

import httpx

from app.services.fixtures import load_lora_fixture


async def search_repositories(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            response = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "order": "desc", "per_page": max_results},
            )
            response.raise_for_status()
            repos = response.json().get("items", [])
            return [_normalize_repo(repo, query) for repo in repos]
    except Exception:
        return [load_lora_fixture()["code_repo"]]


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

