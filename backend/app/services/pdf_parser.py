from __future__ import annotations

import re

from app.models import Citation, PaperSection, new_id


SECTION_NAMES = [
    "abstract",
    "introduction",
    "background",
    "related work",
    "related works",
    "method",
    "methods",
    "methodology",
    "approach",
    "experiments",
    "experimental",
    "experimental setup",
    "evaluation",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
]

# Matches optional section number prefix ("1 ", "2.1 ", "A. ") then the section name alone on the line.
# Handles uppercase (INTRODUCTION), title case (Introduction), lowercase (introduction).
_SECTION_RE = re.compile(
    r"(?im)^(?:\d[\d.]*\.?\s+|[A-Z]\.\s+)?(?P<title>"
    + "|".join(re.escape(s) for s in SECTION_NAMES)
    + r")\s*$"
)

# Matches [N] Author, Title, Venue, Year multi-line bibliography entries.
_BIBLIO_ENTRY_RE = re.compile(
    r"^\s*\[(\d+)\]\s+(.+?)(?=\n\s*\[\d+\]|\Z)",
    re.MULTILINE | re.DOTALL,
)


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes using PyMuPDF (fitz). Returns empty string on failure."""
    try:
        import fitz  # type: ignore

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def split_into_sections(text: str) -> list[PaperSection]:
    """
    Split paper text into named sections.

    Handles:
    - Numbered headings: "1 Introduction", "2.1 Related Work"
    - Plain headings on their own line
    - Upper/lower/title case variants
    """
    if not text.strip():
        return []

    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [
            PaperSection(
                id="sec_text",
                title="Paper Text",
                type="body",
                text=text.strip()[:8000],
                start_offset=0,
                end_offset=min(len(text), 8000),
            )
        ]

    seen: set[str] = set()
    sections: list[PaperSection] = []
    for i, match in enumerate(matches):
        title = match.group("title").strip()
        canonical = title.lower()
        if canonical in seen:
            continue
        seen.add(canonical)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        safe = canonical.replace(" ", "_")
        sections.append(
            PaperSection(
                id=f"sec_{safe}",
                title=title.title(),
                type=safe,
                text=text[start:end].strip()[:8000],
                start_offset=start,
                end_offset=end,
            )
        )
    return sections


def extract_citations(text: str, sections: list[PaperSection]) -> list[Citation]:
    """
    Extract citations from paper text.

    Supports:
    - Numeric: [1], [2,3], [1-3]
    - Author-year: Author et al. (2021), (Smith, 2020)
    - Bibliography line enrichment for numeric citations
    """
    citations: dict[str, Citation] = {}

    # Numeric citations: [1], [2,3], [1-3]
    for match in re.finditer(r"\[(\d{1,3}(?:\s*[,\-]\s*\d{1,3})*)\]", text):
        for num in _expand_nums(match.group(1)):
            cid = f"cit_{num}"
            if cid not in citations:
                citations[cid] = Citation(
                    id=cid,
                    raw=f"[{num}]",
                    context_snippet=_snippet(text, match.start(), match.end()),
                )

    # Author-year citations: Author et al. (2021), (Smith, 2020)
    author_year_re = re.compile(
        r"([A-Z][A-Za-z\-]+(?:\s+et\s+al\.?)?\s*[,(]\s*\d{4}[),]?)"
    )
    for match in author_year_re.finditer(text):
        raw = match.group(1).strip().rstrip(",)")
        year_m = re.search(r"(\d{4})", raw)
        # Deduplicate by slug
        slug = re.sub(r"\W+", "_", raw.lower())[:32]
        cid = f"cit_a_{slug}"
        if cid not in citations:
            citations[cid] = Citation(
                id=cid,
                raw=raw,
                year=int(year_m.group(1)) if year_m else None,
                context_snippet=_snippet(text, match.start(), match.end()),
            )

    # Enrich numeric citations using bibliography section
    _enrich_from_bibliography(text, citations)

    return list(citations.values())


def _expand_nums(raw: str) -> list[str]:
    """Expand '1,3' → ['1','3'] and '1-3' → ['1','2','3']."""
    result: list[str] = []
    for part in re.split(r",", raw):
        part = part.strip()
        m = re.match(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            result.extend(str(i) for i in range(lo, min(hi + 1, lo + 10)))
        else:
            result.append(part)
    return result


def _enrich_from_bibliography(text: str, citations: dict[str, Citation]) -> None:
    """Parse bibliography lines to backfill title/year onto numeric citations."""
    for match in _BIBLIO_ENTRY_RE.finditer(text):
        num = match.group(1)
        entry = match.group(2).replace("\n", " ").strip()
        cid = f"cit_{num}"
        if cid not in citations:
            continue
        cit = citations[cid]
        if cit.title:
            continue
        # Heuristic: look for a capitalized phrase 10-100 chars ending with a period
        title_m = re.search(r"[A-Z][^.]{10,100}\.", entry)
        if title_m:
            cit.title = title_m.group(0).rstrip(".").strip()[:160]
        year_m = re.search(r"\b(19|20)\d{2}\b", entry)
        if year_m:
            cit.year = int(year_m.group(0))
        # First comma-delimited chunk is likely authors
        author_chunk = entry.split(".")[0] if "." in entry else ""
        if author_chunk and not cit.authors:
            cit.authors = [a.strip() for a in author_chunk.split(",") if a.strip()][:4]


def _snippet(text: str, start: int, end: int, width: int = 160) -> str:
    return " ".join(text[max(0, start - width) : min(len(text), end + width)].split())
