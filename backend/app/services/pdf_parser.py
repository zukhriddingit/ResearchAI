from __future__ import annotations

import re

from app.models import Citation, PaperSection, new_id


SECTION_NAMES = [
    "abstract",
    "introduction",
    "background",
    "related work",
    "method",
    "methodology",
    "approach",
    "experiments",
    "evaluation",
    "results",
    "discussion",
    "conclusion",
    "references",
]


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    try:
        import fitz  # type: ignore

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def split_into_sections(text: str) -> list[PaperSection]:
    if not text.strip():
        return []

    heading_pattern = re.compile(
        r"(?im)^(?P<title>" + "|".join(re.escape(name) for name in SECTION_NAMES) + r")\s*$"
    )
    matches = list(heading_pattern.finditer(text))
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

    sections: list[PaperSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group("title").strip()
        sections.append(
            PaperSection(
                id=f"sec_{title.lower().replace(' ', '_')}",
                title=title.title(),
                type=title.lower().replace(" ", "_"),
                text=text[start:end].strip()[:8000],
                start_offset=start,
                end_offset=end,
            )
        )
    return sections


def extract_citations(text: str, sections: list[PaperSection]) -> list[Citation]:
    citations: dict[str, Citation] = {}
    for match in re.finditer(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]", text):
        raw = match.group(0)
        cid = f"cit_{match.group(1).replace(',', '_').replace(' ', '')}"
        citations[cid] = Citation(
            id=cid,
            raw=raw,
            context_snippet=_snippet(text, match.start(), match.end()),
        )

    for match in re.finditer(r"([A-Z][A-Za-z-]+ et al\.,?\s*\(?\d{4}\)?)", text):
        raw = match.group(1)
        cid = f"cit_{new_id('author')}"
        citations[cid] = Citation(id=cid, raw=raw, context_snippet=_snippet(text, match.start(), match.end()))

    return list(citations.values())


def _snippet(text: str, start: int, end: int, width: int = 160) -> str:
    return " ".join(text[max(0, start - width) : min(len(text), end + width)].split())

