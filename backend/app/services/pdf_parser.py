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
    "appendix",
    "references",
]

UNNUMBERED_SECTION_NAMES = {name for name in SECTION_NAMES if name != "method"}

SECTION_TYPE_ALIASES = {
    "methods": "method",
    "methodology": "method",
    "approach": "method",
}

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

    headings = _section_headings(text)
    if not headings:
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
    for index, heading in enumerate(headings):
        start = heading["end"]
        end = headings[index + 1]["start"] if index + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        title = str(heading["title"])
        section_type = str(heading["type"])
        sections.append(
            PaperSection(
                id=f"sec_{index + 1}_{section_type}",
                title=title,
                type=section_type,
                text=body[:8000],
                start_offset=start,
                end_offset=end,
            )
        )
    return sections


def _section_headings(text: str) -> list[dict[str, object]]:
    headings: list[dict[str, object]] = []
    lines = _line_spans(text)
    after_appendix = False

    for index, (start, end, line) in enumerate(lines):
        previous_line = lines[index - 1][2] if index > 0 else ""
        next_line = lines[index + 1][2] if index + 1 < len(lines) else ""
        heading = _parse_section_heading(line, previous_line, next_line, after_appendix)
        if not heading:
            continue
        if heading["type"] == "appendix":
            after_appendix = True
        headings.append({"start": start, "end": end, **heading})

    return _dedupe_close_headings(headings)


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for raw_line in text.splitlines(keepends=True):
        start = cursor
        cursor += len(raw_line)
        spans.append((start, cursor, raw_line.rstrip("\r\n")))
    return spans


def _parse_section_heading(line: str, previous_line: str, next_line: str, after_appendix: bool) -> dict[str, str] | None:
    clean = _clean_heading_line(line)
    if not clean or len(clean) > 110:
        return None
    lower = clean.lower().strip(": ")

    if lower in UNNUMBERED_SECTION_NAMES and not _looks_like_table_header(clean, previous_line, next_line):
        return {"title": clean.title(), "type": _section_type(clean)}

    numbered = re.match(r"^(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<title>[A-Z][A-Za-z0-9][A-Za-z0-9:()&,\-/ ]{2,90})$", clean)
    if numbered:
        title = _normalize_title(numbered.group("title"))
        if _looks_like_section_title(title):
            return {"title": title, "type": _section_type(title)}

    appendix = re.match(r"^(?P<label>[A-Z])\.\s+(?P<title>[A-Z][A-Za-z0-9][A-Za-z0-9:()&,\-/ ]{2,90})$", clean)
    if after_appendix and appendix:
        title = _normalize_title(appendix.group("title"))
        if _looks_like_section_title(title):
            return {"title": title, "type": _section_type(title)}

    return None


def _dedupe_close_headings(headings: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    for heading in headings:
        previous = deduped[-1] if deduped else None
        if previous and heading["type"] == previous["type"] and int(heading["start"]) - int(previous["start"]) < 120:
            previous.update(heading)
            continue
        deduped.append(heading)
    return deduped


def _clean_heading_line(line: str) -> str:
    line = line.replace("\u00a0", " ").replace("\u2009", " ").replace("\ufb01", "fi").replace("\ufb02", "fl")
    return re.sub(r"\s+", " ", line).strip()


def _looks_like_section_title(title: str) -> bool:
    if not title or len(title) < 4 or len(title) > 100:
        return False
    if title.endswith("."):
        return False
    if "," in title or re.search(r"\b(we|our|this|these|those)\b", title, flags=re.IGNORECASE):
        return False
    lower = title.lower()
    if lower.startswith(("table ", "figure ", "fig. ", "algorithm ")):
        return False
    letters = sum(1 for char in title if char.isalpha())
    if letters < 4 or letters / max(len(title), 1) < 0.35:
        return False
    return True


def _looks_like_table_header(line: str, previous_line: str, next_line: str) -> bool:
    context = f"{previous_line} {line} {next_line}".lower()
    table_terms = [
        "flops",
        "#param",
        "#params",
        "top-1",
        "acc.",
        "schedule",
        " ap ",
        "ap50",
        "ap75",
        "miou",
        "table ",
        "imagenet-1k classification",
        "object detection",
    ]
    return any(term in context for term in table_terms)


def _section_type(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return SECTION_TYPE_ALIASES.get(normalized, normalized or "section")


def extract_citations(text: str, sections: list[PaperSection]) -> list[Citation]:
    citations: dict[str, Citation] = {}
    reference_start = _references_start(text)
    references = _extract_reference_metadata(text)
    author_year_references = _extract_author_year_reference_metadata(text)

    for match in re.finditer(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]", text):
        if reference_start is not None and match.start() >= reference_start:
            continue
        raw = match.group(0)
        numbers = _citation_numbers(match.group(1))
        cid = f"cit_{match.group(1).replace(',', '_').replace(' ', '')}"
        metadata = _citation_metadata(numbers, references)
        if cid in citations:
            continue
        citations[cid] = Citation(
            id=cid,
            raw=raw,
            title=metadata.get("title"),
            authors=metadata.get("authors", []),
            year=metadata.get("year"),
            context_snippet=_snippet(text, match.start(), match.end()),
        )

    for match in re.finditer(r"([A-Z][A-Za-z-]+ et al\.,?\s*\(?\d{4}\)?)", text):
        if reference_start is not None and match.start() >= reference_start:
            continue
        raw = match.group(1)
        cid = f"cit_{new_id('author')}"
        metadata = _author_year_citation_metadata(raw, author_year_references)
        citations[cid] = Citation(
            id=cid,
            raw=raw,
            title=metadata.get("title"),
            authors=metadata.get("authors", []),
            year=metadata.get("year"),
            context_snippet=_snippet(text, match.start(), match.end()),
        )

    return list(citations.values())


def _references_start(text: str) -> int | None:
    matches = list(re.finditer(r"(?im)^references\s*$", text))
    return matches[-1].end() if matches else None


def _extract_reference_metadata(text: str) -> dict[str, dict[str, object]]:
    start = _references_start(text)
    if start is None:
        return {}

    reference_text = text[start:]
    entries = re.finditer(r"(?ms)^\[(?P<number>\d{1,3})\]\s+(?P<body>.*?)(?=^\[\d{1,3}\]\s+|\Z)", reference_text)
    metadata: dict[str, dict[str, object]] = {}
    for match in entries:
        body = _clean_reference_entry(match.group("body"))
        if not body:
            continue
        title = _reference_title(body)
        if not title:
            continue
        metadata[match.group("number")] = {
            "title": title,
            "authors": _reference_authors(body),
            "year": _reference_year(body),
        }
    return metadata


def _extract_author_year_reference_metadata(text: str) -> dict[str, dict[str, object]]:
    start = _references_start(text)
    if start is None:
        return {}

    metadata: dict[str, dict[str, object]] = {}
    for body in _unnumbered_reference_entries(text[start:]):
        title = _reference_title(body)
        year = _reference_year(body)
        first_author = _reference_first_author(body)
        if not title or not year or not first_author:
            continue
        key = f"{first_author.lower()}:{year}"
        metadata.setdefault(
            key,
            {
                "title": title,
                "authors": _reference_authors(body),
                "year": year,
            },
        )
    return metadata


def _unnumbered_reference_entries(reference_text: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"(?m)^[A-Z][A-Za-z'’-]+,\s+[A-Z]", reference_text)]
    if not starts:
        return []
    entries: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(reference_text)
        entry = _clean_reference_entry(reference_text[start:end])
        if entry and not entry.startswith("["):
            entries.append(entry)
    return entries


def _citation_numbers(raw_numbers: str) -> list[str]:
    return [number.strip() for number in raw_numbers.split(",") if number.strip()]


def _citation_metadata(numbers: list[str], references: dict[str, dict[str, object]]) -> dict[str, object]:
    matches = [references[number] for number in numbers if number in references]
    if not matches:
        return {}

    titles = [str(item["title"]) for item in matches if item.get("title")]
    if len(matches) == 1:
        return {
            "title": titles[0] if titles else None,
            "authors": matches[0].get("authors", []),
            "year": matches[0].get("year"),
        }

    return {
        "title": "; ".join(titles[:3]),
        "authors": matches[0].get("authors", []),
        "year": matches[0].get("year"),
    }


def _author_year_citation_metadata(raw: str, references: dict[str, dict[str, object]]) -> dict[str, object]:
    match = re.search(r"(?P<author>[A-Z][A-Za-z'’-]+)\s+et al\.,?\s*\(?(?P<year>\d{4})", raw)
    if not match:
        return {}
    return references.get(f"{match.group('author').lower()}:{match.group('year')}", {})


def _clean_reference_entry(entry: str) -> str:
    entry = (
        entry.replace("\u00a0", " ")
        .replace("\u2009", " ")
        .replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
    )
    entry = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", entry)
    entry = re.sub(r"\s+", " ", entry).strip()
    return entry.strip(" .")


def _reference_title(entry: str) -> str | None:
    parts = _reference_sentence_parts(entry)
    for part in parts[1:5]:
        title = _normalize_title(part)
        if _looks_like_reference_title(title):
            return title

    if len(parts) == 1:
        title = _normalize_title(parts[0])
        if _looks_like_reference_title(title) and not _looks_like_author_line(title):
            return title

    return None


def _looks_like_reference_title(title: str) -> bool:
    lower = title.lower().strip()
    if not lower or len(title) < 4 or len(title) > 220:
        return False
    if _looks_like_author_line(title):
        return False
    if lower.startswith(("in ", "pages ", "volume ", "arxiv preprint", "ieee ", "springer", "proceedings")):
        return False
    if re.fullmatch(r"(19|20)\d{2}.*", lower):
        return False
    letters = sum(1 for char in title if char.isalpha())
    return letters >= 4 and letters / max(len(title), 1) >= 0.35


def _reference_authors(entry: str) -> list[str]:
    first_sentence = _reference_sentence_parts(entry)[0] if _reference_sentence_parts(entry) else ""
    first_sentence = re.sub(r"\bet al\b\.?", "et al.", first_sentence, flags=re.IGNORECASE)
    chunks = re.split(r",\s+|\s+and\s+|&", first_sentence)
    authors = [_normalize_title(chunk) for chunk in chunks]
    return [author for author in authors if 2 <= len(author) <= 80][:8]


def _reference_first_author(entry: str) -> str | None:
    match = re.match(r"([A-Z][A-Za-z'’-]+),", entry)
    return match.group(1) if match else None


def _reference_sentence_parts(entry: str) -> list[str]:
    return [part.strip() for part in re.split(r"\.\s+", entry) if part.strip()]


def _reference_year(entry: str) -> int | None:
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", entry)
    return int(years[-1]) if years else None


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
