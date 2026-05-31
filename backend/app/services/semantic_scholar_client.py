from __future__ import annotations

import os
from typing import Any

import httpx


BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,abstract,year,authors,citationCount,referenceCount,influentialCitationCount,url,openAccessPdf"


async def search_paper(query: str, limit: int = 5) -> list[dict[str, Any]]:
    headers = _headers()
    params = {"query": query, "limit": limit, "fields": FIELDS}
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
            response = await client.get(f"{BASE_URL}/paper/search", params=params)
            response.raise_for_status()
            return response.json().get("data", [])
    except Exception:
        return []


async def get_paper_details(paper_id_or_arxiv_id: str) -> dict[str, Any]:
    headers = _headers()
    paper_id = paper_id_or_arxiv_id
    if paper_id_or_arxiv_id and paper_id_or_arxiv_id[0].isdigit():
        paper_id = f"ARXIV:{paper_id_or_arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
            response = await client.get(f"{BASE_URL}/paper/{paper_id}", params={"fields": FIELDS})
            response.raise_for_status()
            return response.json()
    except Exception:
        return {}


async def get_references(paper_id: str) -> list[dict[str, Any]]:
    headers = _headers()
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
            response = await client.get(f"{BASE_URL}/paper/{paper_id}/references", params={"fields": FIELDS})
            response.raise_for_status()
            return response.json().get("data", [])
    except Exception:
        return []


def _headers() -> dict[str, str]:
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": api_key} if api_key else {}

