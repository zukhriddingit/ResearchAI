from __future__ import annotations

import re
from typing import Any

import httpx


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5})(v\d+)?")
_AUTHOR_RE = re.compile(r"<author>.*?<name>(.*?)</name>.*?</author>", re.DOTALL)
_PUBLISHED_RE = re.compile(r"<published>(\d{4})-(\d{2})-(\d{2})")


def normalize_arxiv_id(source: str) -> str | None:
    match = ARXIV_ID_RE.search(source)
    return match.group("id") if match else None


async def fetch_arxiv_metadata(arxiv_id: str) -> dict[str, Any]:
    params = {"id_list": arxiv_id}
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(ARXIV_API_URL, params=params)
        response.raise_for_status()
    text = response.text
    published = _PUBLISHED_RE.search(text)
    return {
        "arxiv_id": arxiv_id,
        "raw_atom": text,
        "title": _between(text, "<title>", "</title>", skip_first=True),
        "abstract": _between(text, "<summary>", "</summary>"),
        "authors": [author.strip() for author in _AUTHOR_RE.findall(text) if author.strip()],
        "year": int(published.group(1)) if published else None,
    }


async def fetch_arxiv_pdf(arxiv_id: str) -> bytes | None:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    except Exception:
        return None


def _between(text: str, start: str, end: str, *, skip_first: bool = False) -> str | None:
    start_index = text.find(start)
    if start_index < 0:
        return None
    if skip_first:
        start_index = text.find(start, start_index + len(start))
        if start_index < 0:
            return None
    start_index += len(start)
    end_index = text.find(end, start_index)
    if end_index < 0:
        return None
    return " ".join(text[start_index:end_index].split())


async def fetch_arxiv_latex_source(arxiv_id: str) -> str:
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return _decode_arxiv_source(response.content)
    except Exception:
        return ""


def _decode_arxiv_source(raw: bytes) -> str:
    import gzip
    import io
    import tarfile

    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tex_members = [member for member in tar.getmembers() if member.name.endswith(".tex")]
            tex_members.sort(key=lambda member: member.size, reverse=True)
            if tex_members:
                extracted = tar.extractfile(tex_members[0])
                if extracted:
                    return extracted.read().decode("utf-8", errors="replace")
    except Exception:
        pass

    try:
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
        if "\\documentclass" in text or "\\begin{document}" in text:
            return text
    except Exception:
        pass
    return ""
