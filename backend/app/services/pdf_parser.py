from __future__ import annotations

import base64
import re
from typing import Any

from app.models import Citation, FigureExtract, PaperSection, TableExtract, new_id


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

_SECTION_RE = re.compile(
    r"(?im)^(?:\d[\d.]*\.?\s+|[A-Z]\.\s+)?(?P<title>"
    + "|".join(re.escape(s) for s in SECTION_NAMES)
    + r")\s*$"
)

_BIBLIO_ENTRY_RE = re.compile(
    r"^\s*\[(\d+)\]\s+(.+?)(?=\n\s*\[\d+\]|\Z)",
    re.MULTILINE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes using PyMuPDF."""
    try:
        import fitz  # type: ignore
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

def split_into_sections(text: str) -> list[PaperSection]:
    """
    Split paper text into named sections.
    Handles numbered headings (1 Introduction, 2.1 Related Work) and all-caps.
    """
    if not text.strip():
        return []

    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [PaperSection(id="sec_text", title="Paper Text", type="body",
                             text=text.strip()[:8000], start_offset=0, end_offset=min(len(text), 8000))]

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
        sections.append(PaperSection(id=f"sec_{safe}", title=title.title(), type=safe,
                                     text=text[start:end].strip()[:8000],
                                     start_offset=start, end_offset=end))
    return sections


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------

def extract_citations(text: str, sections: list[PaperSection]) -> list[Citation]:
    """Extract numeric [1] and author-year citations, enrich from bibliography."""
    citations: dict[str, Citation] = {}

    for match in re.finditer(r"\[(\d{1,3}(?:\s*[,\-]\s*\d{1,3})*)\]", text):
        for num in _expand_nums(match.group(1)):
            cid = f"cit_{num}"
            if cid not in citations:
                citations[cid] = Citation(id=cid, raw=f"[{num}]",
                                          context_snippet=_snippet(text, match.start(), match.end()))

    author_year_re = re.compile(r"([A-Z][A-Za-z\-]+(?:\s+et\s+al\.?)?\s*[,(]\s*\d{4}[),]?)")
    for match in author_year_re.finditer(text):
        raw = match.group(1).strip().rstrip(",)")
        year_m = re.search(r"(\d{4})", raw)
        slug = re.sub(r"\W+", "_", raw.lower())[:32]
        cid = f"cit_a_{slug}"
        if cid not in citations:
            citations[cid] = Citation(id=cid, raw=raw,
                                      year=int(year_m.group(1)) if year_m else None,
                                      context_snippet=_snippet(text, match.start(), match.end()))

    _enrich_from_bibliography(text, citations)
    return list(citations.values())


# ---------------------------------------------------------------------------
# Figure extraction
# ---------------------------------------------------------------------------

def extract_figures_from_pdf_bytes(
    pdf_bytes: bytes,
    sections: list[PaperSection],
    max_figures: int = 12,
) -> list[FigureExtract]:
    """
    Extract figures from a PDF as base64 PNG crops, associated with sections.
    Uses PyMuPDF's image info API and renders image bounding boxes.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return []

    figures: list[FigureExtract] = []
    total_pages = len(doc)

    for page_num in range(total_pages):
        if len(figures) >= max_figures:
            break
        page = doc[page_num]

        for img_info in page.get_image_info():
            if len(figures) >= max_figures:
                break
            bbox = img_info.get("bbox")
            if not bbox:
                continue
            rect = fitz.Rect(bbox)
            # Skip tiny images (likely icons or decorations, not figures)
            if rect.width < 80 or rect.height < 60:
                continue

            # Render the cropped figure region as PNG (scale 1.5x for quality)
            mat = fitz.Matrix(1.5, 1.5)
            clip = rect
            try:
                pix = page.get_pixmap(matrix=mat, clip=clip, colorspace=fitz.csRGB)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()
            except Exception:
                continue

            # Find caption: text block immediately below the figure
            caption = _find_caption_near_rect(page, rect)
            section_id = _page_to_section_id(page_num, total_pages, sections)

            figures.append(FigureExtract(
                caption=caption,
                image_b64=img_b64,
                page=page_num,
                section_id=section_id,
            ))

    doc.close()
    return figures


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def extract_tables_from_pdf_bytes(
    pdf_bytes: bytes,
    sections: list[PaperSection],
    max_tables: int = 8,
) -> list[TableExtract]:
    """
    Extract tables from a PDF as structured rows using PyMuPDF's find_tables().
    Also renders each table as a base64 PNG crop for vision critique.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return []

    tables: list[TableExtract] = []
    total_pages = len(doc)

    for page_num in range(total_pages):
        if len(tables) >= max_tables:
            break
        page = doc[page_num]

        try:
            found = page.find_tables()
        except Exception:
            continue

        for tab in found:
            if len(tables) >= max_tables:
                break
            try:
                rows = tab.extract() or []
                # Clean empty rows/cells
                rows = [[str(cell).strip() if cell else "" for cell in row]
                        for row in rows if any(cell for cell in row)]
            except Exception:
                rows = []

            # Render table region as PNG
            img_b64 = ""
            try:
                mat = fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat, clip=tab.bbox, colorspace=fitz.csRGB)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()
            except Exception:
                pass

            caption = _find_caption_near_rect(page, fitz.Rect(tab.bbox), look_above=True)
            section_id = _page_to_section_id(page_num, total_pages, sections)

            tables.append(TableExtract(
                caption=caption,
                rows=rows[:30],   # cap rows to avoid giant payloads
                image_b64=img_b64,
                section_id=section_id,
            ))

    doc.close()
    return tables


# ---------------------------------------------------------------------------
# Helper: attach figures/tables to sections
# ---------------------------------------------------------------------------

def attach_visuals_to_sections(
    sections: list[PaperSection],
    figures: list[FigureExtract],
    tables: list[TableExtract],
) -> None:
    """Mutate sections in-place, placing each visual into its owning section."""
    sec_map = {s.id: s for s in sections}
    for fig in figures:
        if fig.section_id and fig.section_id in sec_map:
            sec_map[fig.section_id].figures.append(fig)
    for tab in tables:
        if tab.section_id and tab.section_id in sec_map:
            sec_map[tab.section_id].tables.append(tab)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_caption_near_rect(page: Any, rect: Any, look_above: bool = False) -> str | None:
    """Find a figure/table caption near a bounding rect."""
    try:
        import fitz  # type: ignore
        blocks = page.get_text("blocks")
        target_y = rect.y0 if look_above else rect.y1
        best: str | None = None
        best_dist = float("inf")
        for block in blocks:
            bx0, by0, bx1, by1, text, *_ = block
            text = text.strip()
            if not text:
                continue
            low = text.lower()
            if not (low.startswith(("figure", "fig.", "fig ", "table", "tab."))):
                continue
            block_y = by0 if look_above else by1
            dist = abs(block_y - target_y)
            if dist < 60 and dist < best_dist:
                best_dist = dist
                best = text[:300]
        return best
    except Exception:
        return None


def _page_to_section_id(page_num: int, total_pages: int, sections: list[PaperSection]) -> str | None:
    """Estimate which section a page belongs to by proportional position."""
    if not sections:
        return None
    frac = page_num / max(total_pages - 1, 1)
    idx = int(frac * (len(sections) - 1))
    return sections[min(idx, len(sections) - 1)].id


def _expand_nums(raw: str) -> list[str]:
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
    for match in _BIBLIO_ENTRY_RE.finditer(text):
        num = match.group(1)
        entry = match.group(2).replace("\n", " ").strip()
        cid = f"cit_{num}"
        if cid not in citations:
            continue
        cit = citations[cid]
        if cit.title:
            continue
        title_m = re.search(r"[A-Z][^.]{10,100}\.", entry)
        if title_m:
            cit.title = title_m.group(0).rstrip(".").strip()[:160]
        year_m = re.search(r"\b(19|20)\d{2}\b", entry)
        if year_m:
            cit.year = int(year_m.group(0))
        author_chunk = entry.split(".")[0] if "." in entry else ""
        if author_chunk and not cit.authors:
            cit.authors = [a.strip() for a in author_chunk.split(",") if a.strip()][:4]


def _snippet(text: str, start: int, end: int, width: int = 160) -> str:
    return " ".join(text[max(0, start - width): min(len(text), end + width)].split())
