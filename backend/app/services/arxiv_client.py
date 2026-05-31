from __future__ import annotations

import re
from typing import Any

import httpx

from app.services.weave_tracing import op as weave_op


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5})(v\d+)?")
_AUTHOR_RE = re.compile(r"<author>.*?<name>(.*?)</name>.*?</author>", re.DOTALL)
_PUBLISHED_RE = re.compile(r"<published>(\d{4})-(\d{2})-(\d{2})")


def normalize_arxiv_id(source: str) -> str | None:
    """Extract bare arXiv ID from URLs like https://arxiv.org/abs/2106.09685 or plain IDs."""
    match = ARXIV_ID_RE.search(source)
    return match.group("id") if match else None


@weave_op
async def fetch_arxiv_metadata(arxiv_id: str) -> dict[str, Any]:
    """Fetch paper metadata from the arXiv Atom API. Returns title, abstract, authors, year."""
    params = {"id_list": arxiv_id}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()
        text = response.text
    except Exception:
        return {"arxiv_id": arxiv_id, "title": None, "abstract": None, "authors": [], "year": None, "raw_atom": ""}

    authors = _AUTHOR_RE.findall(text)
    published = _PUBLISHED_RE.search(text)
    year = int(published.group(1)) if published else None

    return {
        "arxiv_id": arxiv_id,
        "raw_atom": text,
        "title": _between(text, "<title>", "</title>", skip_first=True),
        "abstract": _between(text, "<summary>", "</summary>"),
        "authors": [a.strip() for a in authors if a.strip()],
        "year": year,
    }


@weave_op
async def fetch_arxiv_pdf(arxiv_id: str) -> bytes | None:
    """Download PDF bytes from arXiv. Returns None on failure (don't block demo on this)."""
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.content
    except Exception:
        return None


@weave_op
async def fetch_arxiv_latex_source(arxiv_id: str) -> str:
    """
    Download the arxiv LaTeX source for a paper and return the contents of the
    main .tex file as a single string.  Returns "" on any failure.

    arxiv.org/e-print/{id} returns either:
      - a gzip-compressed single .tex file
      - a gzip-compressed tar archive containing multiple files
    """
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            raw = response.content
    except Exception:
        return ""

    return _decode_arxiv_source(raw)


def _decode_arxiv_source(raw: bytes) -> str:
    """Decode a raw arxiv e-print download into its main LaTeX source."""
    import gzip
    import io
    import tarfile

    # Try as tar.gz first
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            # Prefer the largest .tex file (usually the main source)
            tex_members = [m for m in tar.getmembers() if m.name.endswith(".tex")]
            if not tex_members:
                return ""
            tex_members.sort(key=lambda m: m.size, reverse=True)
            f = tar.extractfile(tex_members[0])
            if f:
                return f.read().decode("utf-8", errors="replace")
    except Exception:
        pass

    # Try as plain .gz (single file)
    try:
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
        if "\\documentclass" in text or "\\begin{document}" in text:
            return text
    except Exception:
        pass

    return ""


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
