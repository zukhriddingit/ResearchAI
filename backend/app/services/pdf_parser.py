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

TITLE_STOP_HEADINGS = {
    "abstract",
    "introduction",
    "keywords",
    "references",
    "acknowledgements",
    "acknowledgments",
}

TITLE_SKIP_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^\s*\d+\s*$",
        r"^\s*\d{4}\.\d{4,5}(v\d+)?(\s|\b)",
        r"\barxiv\b|arxiv:",
        r"\bdoi\b|https?://|www\.",
        r"@",
        r"\b(submitted|accepted|preprint|proceedings|conference|workshop|copyright|license)\b",
        r"\b(university|institute|department|school|college|faculty|laboratory|centre|center)\b",
        r"\b(github|openreview|neurips|iclr|icml|acl|emnlp|cvpr|eccv|iccv)\b",
    ]
]

TITLE_WORDS = {
    "adaptation",
    "adversarial",
    "alignment",
    "analysis",
    "attention",
    "benchmark",
    "code",
    "data",
    "diffusion",
    "efficient",
    "evaluation",
    "feature",
    "features",
    "fine-tuning",
    "generation",
    "generative",
    "graph",
    "grounding",
    "inference",
    "language",
    "learning",
    "llm",
    "lora",
    "model",
    "models",
    "neural",
    "paper",
    "reasoning",
    "reinforcement",
    "representation",
    "retrieval",
    "scaling",
    "supervision",
    "transformer",
    "vision",
}


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    try:
        import fitz  # type: ignore

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def extract_title_from_text(text: str) -> str | None:
    lines = [_clean_title_line(line) for line in text.replace("\r", "\n").split("\n")[:120]]
    lines = [line for line in lines if line]
    if not lines:
        return None

    stop_index = _front_matter_stop_index(lines)
    front_matter = lines[:stop_index] if stop_index else lines[:60]
    scored: list[tuple[int, int, str]] = []

    for index, line in enumerate(front_matter):
        if _reject_title_line(line):
            continue
        scored.append((_score_title_candidate(line, index, stop_index), index, line))

        if index + 1 < len(front_matter) and _valid_title_continuation(front_matter[index + 1]):
            two_line = f"{line} {front_matter[index + 1]}"
            if not _reject_title_line(two_line):
                scored.append((_score_title_candidate(two_line, index, stop_index) + 2, index, two_line))

        if (
            index + 2 < len(front_matter)
            and _valid_title_continuation(front_matter[index + 1])
            and _valid_title_continuation(front_matter[index + 2])
        ):
            three_line = f"{line} {front_matter[index + 1]} {front_matter[index + 2]}"
            if not _reject_title_line(three_line):
                scored.append((_score_title_candidate(three_line, index, stop_index) + 1, index, three_line))

    if not scored:
        for line in lines[:20]:
            if not _reject_title_line(line):
                return _normalize_title(line)
        return None

    _score, _index, title = max(scored, key=lambda item: (item[0], -item[1]))
    return _normalize_title(title)


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


def _clean_title_line(line: str) -> str:
    line = line.replace("\u00a0", " ").replace("\u2009", " ").replace("\ufb01", "fi").replace("\ufb02", "fl")
    line = re.sub(r"\s+", " ", line).strip()
    return line.strip(" .")


def _front_matter_stop_index(lines: list[str]) -> int:
    for index, line in enumerate(lines[:80]):
        normalized = re.sub(r"^\d+\.?\s+", "", line.lower()).strip(": ")
        if normalized in TITLE_STOP_HEADINGS:
            return index
    return 0


def _reject_title_line(line: str) -> bool:
    normalized = line.strip()
    lower = normalized.lower().strip(": ")
    if not normalized or lower in TITLE_STOP_HEADINGS:
        return True
    if len(normalized) < 8 or len(normalized) > 220:
        return True
    if any(pattern.search(normalized) for pattern in TITLE_SKIP_PATTERNS):
        return True
    letters = sum(1 for char in normalized if char.isalpha())
    if letters < 6 or letters / max(len(normalized), 1) < 0.35:
        return True
    if _looks_like_author_line(normalized):
        return True
    return False


def _valid_title_continuation(line: str) -> bool:
    normalized = line.strip()
    lower = normalized.lower().strip(": ")
    if not normalized or lower in TITLE_STOP_HEADINGS:
        return False
    if len(normalized) < 3 or len(normalized) > 120:
        return False
    if any(pattern.search(normalized) for pattern in TITLE_SKIP_PATTERNS):
        return False
    if _looks_like_author_line(normalized):
        return False
    letters = sum(1 for char in normalized if char.isalpha())
    return letters >= 3


def _looks_like_author_line(line: str) -> bool:
    if re.search(r"\b[A-Z][A-Za-z'-]+[0-9*†‡]", line):
        return True

    words = re.findall(r"[A-Za-z][A-Za-z'-]*", line)
    if len(words) < 2:
        return False

    has_title_word = bool({word.lower() for word in words} & TITLE_WORDS)
    capitalized = [word for word in words if word[:1].isupper() or word.isupper()]
    short_author_tokens = [word for word in words if len(word) <= 3 or re.fullmatch(r"[A-Z]\.?", word)]
    comma_or_and = "," in line or " and " in line.lower() or " & " in line

    if not has_title_word and comma_or_and and len(capitalized) / len(words) > 0.65:
        return True
    if not has_title_word and len(words) <= 8 and len(capitalized) / len(words) > 0.8 and len(short_author_tokens) <= 2:
        return True
    return False


def _score_title_candidate(line: str, index: int, stop_index: int) -> int:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", line)
    lower_words = {word.lower() for word in words}
    score = 0

    if 18 <= len(line) <= 150:
        score += 4
    elif 8 <= len(line) <= 200:
        score += 1
    if 3 <= len(words) <= 18:
        score += 4
    elif len(words) > 24:
        score -= 4
    if not line.endswith("."):
        score += 2
    if ":" in line:
        score += 1
    if lower_words & TITLE_WORDS:
        score += 4
    if stop_index:
        score += max(0, 4 - min(abs(stop_index - index), 4))
    if index <= 8:
        score += 2
    if re.search(r"\b(we|this|our|in this paper)\b", line, re.IGNORECASE):
        score -= 3
    return score


def _normalize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" .")
    title = re.sub(r"\s+([:;,])", r"\1", title)
    return title
