from __future__ import annotations

import base64
import re
from typing import Any

from app.models import Citation, EquationExtract, FigureExtract, PaperSection, TableExtract, new_id

# ---------------------------------------------------------------------------
# Unicode math character ranges for equation detection
# ---------------------------------------------------------------------------

_MATH_UNICODES = set(
    "∀∁∂∃∄∅∆∇∈∉∊∋"
    "∏∑−∓∗√∛∞∠∧∨∩"
    "∪∫∬∭∴∵∼≈≠≡≤≥"
    "≪≫⊂⊃⊆⊇⊢⊨⋅⋈⌈⌉"
    "⌊⌋⌠⌡⎛⎜⎝⎞⎟⎠"
    "αβγδεζηθικλμ"
    "νξοπρςστυφχψ"
    "ωΑΒΓΔΕΖΗΘΙΚΛ"
    "ΜΝΞΟΠΡΣΤΥΦΧΨΩ"
)

_MATH_FONT_NAMES = ("cmmi", "cmmib", "cmr", "cmsy", "cmex", "msam", "msbm", "symbol", "zapf")
_EQ_LABEL_RE = re.compile(r"\(\s*\d+(?:\.\d+)?\s*\)\s*$")
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'>]+)")
_ARXIV_REF_RE = re.compile(r"arXiv[:\s]+([\d.]+)", re.IGNORECASE)

SECTION_NAMES = [
    "abstract", "introduction", "background", "related work", "related works",
    "method", "methods", "methodology", "approach", "experiments", "experimental",
    "experimental setup", "evaluation", "results", "discussion", "conclusion",
    "conclusions", "appendix", "references", "acknowledgements", "acknowledgments",
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
# Structured extraction from PDF (font-aware)
# ---------------------------------------------------------------------------

def extract_structured_document(pdf_bytes: bytes) -> tuple[list[PaperSection], list[EquationExtract]]:
    """
    Parse a PDF using PyMuPDF's dict output to recover section hierarchy and equations.

    Returns (sections, equations).  Sections have .level=1 for top-level headers,
    .level=2 for subsections.  Equations carry .raw, .label, and context snippets.
    Falls back to plain text split if fitz is unavailable.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        text = extract_text_from_pdf_bytes(pdf_bytes)
        return split_into_sections(text), []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return [], []

    # --- pass 1: collect all spans with font/size info -----------------------
    spans_by_page: list[list[dict]] = []
    for page in doc:
        page_spans: list[dict] = []
        try:
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            spans_by_page.append([])
            continue
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text = ""
                line_size = 0.0
                line_bold = False
                line_math = False
                fonts: list[str] = []
                for span in line.get("spans", []):
                    t = span.get("text", "")
                    line_text += t
                    sz = span.get("size", 0.0)
                    if sz > line_size:
                        line_size = sz
                    flags = span.get("flags", 0)
                    if flags & 16:  # bold flag
                        line_bold = True
                    font_name = span.get("font", "").lower()
                    fonts.append(font_name)
                    if any(mf in font_name for mf in _MATH_FONT_NAMES):
                        line_math = True
                    if any(ch in _MATH_UNICODES for ch in t):
                        line_math = True
                if line_text.strip():
                    page_spans.append({
                        "text": line_text,
                        "size": line_size,
                        "bold": line_bold,
                        "math": line_math,
                        "fonts": fonts,
                    })
        spans_by_page.append(page_spans)
    doc.close()

    all_spans = [s for page in spans_by_page for s in page]
    if not all_spans:
        text = extract_text_from_pdf_bytes(pdf_bytes)
        return split_into_sections(text), []

    # --- determine body font size (most common size rounded to 0.5pt) --------
    from collections import Counter
    size_counts: Counter[float] = Counter()
    for s in all_spans:
        rounded = round(s["size"] * 2) / 2
        size_counts[rounded] += len(s["text"])
    body_size = size_counts.most_common(1)[0][0] if size_counts else 10.0
    h1_threshold = body_size + 1.5   # at least 1.5pt larger → heading
    h2_threshold = body_size + 0.5

    # --- pass 2: build sections and detect equations -------------------------
    sections: list[PaperSection] = []
    equations: list[EquationExtract] = []
    current_title = "Document"
    current_type = "body"
    current_level = 1
    current_lines: list[str] = []
    seen_titles: set[str] = set()

    def _flush(title: str, typ: str, level: int, lines: list[str]) -> None:
        text = "\n".join(lines).strip()
        if not text and not sections:
            return
        safe = re.sub(r"\W+", "_", typ.lower())[:40]
        sec_id = f"sec_{safe}"
        # deduplicate
        base = sec_id
        n = 1
        while sec_id in seen_titles:
            sec_id = f"{base}_{n}"
            n += 1
        seen_titles.add(sec_id)
        sections.append(PaperSection(
            id=sec_id, title=title.strip().title(), type=typ.lower(),
            level=level, text=text[:10000],
        ))

    for span in all_spans:
        text = span["text"].strip()
        if not text:
            continue

        sz = span["size"]
        is_heading = (
            (sz >= h1_threshold or (sz >= h2_threshold and span["bold"]))
            and len(text) < 120
            and not span["math"]
        )

        # Equation detection
        is_equation = (
            span["math"]
            or bool(_EQ_LABEL_RE.search(text))
            or (len(text) < 200 and sum(1 for c in text if c in _MATH_UNICODES) >= 2)
        )

        if is_heading and _looks_like_section_header(text):
            _flush(current_title, current_type, current_level, current_lines)
            current_lines = []
            current_title = text
            current_type = _canonical_section_type(text)
            current_level = 1 if sz >= h1_threshold else 2
        elif is_equation:
            label = (_EQ_LABEL_RE.search(text) or _EQ_LABEL_RE.search(text.rstrip()))
            label_str = label.group(0).strip() if label else ""
            ctx_before = current_lines[-1].strip() if current_lines else ""
            eq = EquationExtract(
                id=new_id("eq"),
                raw=text[:400],
                label=label_str,
                context_before=ctx_before[:300],
                context_after="",   # filled in post-pass below
                section_id=None,    # filled in after sections are built
            )
            equations.append(eq)
            current_lines.append(text)
        else:
            # Fill context_after for the preceding equation
            if equations and not equations[-1].context_after and text:
                equations[-1] = equations[-1].model_copy(update={"context_after": text[:300]})
            current_lines.append(text)

    _flush(current_title, current_type, current_level, current_lines)

    # --- assign equations to sections ----------------------------------------
    if sections and equations:
        # Rough proportional assignment by order
        total_eq = len(equations)
        total_sec = len(sections)
        for i, eq in enumerate(equations):
            sec_idx = min(int(i / total_eq * total_sec), total_sec - 1)
            updated = eq.model_copy(update={"section_id": sections[sec_idx].id})
            equations[i] = updated

    # Ensure we have at least one section
    if not sections:
        sections = [PaperSection(id="sec_body", title="Paper", type="body",
                                 text="\n".join(s["text"] for s in all_spans)[:10000])]

    return sections, equations


def _looks_like_section_header(text: str) -> bool:
    """Heuristic: text looks like a section header."""
    stripped = text.strip().rstrip(".")
    # Known keywords
    lower = stripped.lower()
    if any(lower == kw or lower.startswith(kw + " ") or lower.endswith(" " + kw)
           for kw in SECTION_NAMES):
        return True
    # Numbered like "1 Introduction" or "2.1 Background"
    if re.match(r"^\d[\d.]*\s+\w", stripped):
        return True
    # All-caps short title
    if stripped.isupper() and 3 < len(stripped) < 60:
        return True
    return False


def _canonical_section_type(title: str) -> str:
    lower = re.sub(r"^\d[\d.]*\s*", "", title.strip()).lower()
    for name in SECTION_NAMES:
        if name in lower:
            return name.replace(" ", "_")
    return re.sub(r"\W+", "_", lower)[:30] or "body"


# ---------------------------------------------------------------------------
# Plain text extraction (fallback / used by other parts)
# ---------------------------------------------------------------------------

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    try:
        import fitz  # type: ignore
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Equation extraction from plain LaTeX text (from arxiv source)
# ---------------------------------------------------------------------------

def extract_equations_from_latex(latex_source: str, sections: list[PaperSection]) -> list[EquationExtract]:
    """
    Extract equations from a raw LaTeX source string.
    Handles: \\begin{equation}, \\begin{align}, \\begin{gather}, $$ ... $$, $ ... $
    """
    equations: list[EquationExtract] = []
    total_secs = max(len(sections), 1)

    # Block equations
    block_env_re = re.compile(
        r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?)\}"
        r"(.*?)"
        r"\\end\{\1\}",
        re.DOTALL,
    )
    # Display math $$...$$
    display_re = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)
    # Inline $...$
    inline_re = re.compile(r"(?<!\$)\$([^$\n]{4,120})\$(?!\$)")

    text_chunks = _split_latex_by_context(latex_source)

    for env_match in block_env_re.finditer(latex_source):
        eq_latex = env_match.group(2).strip()
        start = env_match.start()
        ctx_before = latex_source[max(0, start - 300):start].strip().splitlines()
        ctx_after_raw = latex_source[env_match.end():env_match.end() + 300].strip().splitlines()
        label_m = re.search(r"\\label\{([^}]+)\}", eq_latex)
        label_str = label_m.group(1) if label_m else ""
        # Remove label from latex body
        eq_latex_clean = re.sub(r"\\label\{[^}]+\}", "", eq_latex).strip()
        equations.append(EquationExtract(
            id=new_id("eq"),
            raw=_latex_to_text(eq_latex_clean),
            latex=eq_latex_clean[:800],
            label=label_str,
            context_before="\n".join(ctx_before[-3:])[:300],
            context_after="\n".join(ctx_after_raw[:3])[:300],
        ))

    for disp_match in display_re.finditer(latex_source):
        eq_latex = disp_match.group(1).strip()
        if len(eq_latex) < 4:
            continue
        start = disp_match.start()
        ctx_before = latex_source[max(0, start - 200):start].strip()[-200:]
        ctx_after = latex_source[disp_match.end():disp_match.end() + 200].strip()[:200]
        equations.append(EquationExtract(
            id=new_id("eq"),
            raw=_latex_to_text(eq_latex),
            latex=eq_latex[:800],
            label="",
            context_before=ctx_before,
            context_after=ctx_after,
        ))

    # Assign sections by position
    for i, eq in enumerate(equations):
        sec_idx = min(int(i / len(equations) * total_secs), total_secs - 1) if equations else 0
        equations[i] = eq.model_copy(update={"section_id": sections[sec_idx].id if sections else None})

    return equations[:60]  # cap to avoid huge payloads


def _split_latex_by_context(latex: str) -> list[str]:
    """Split latex source into sentence-like chunks for context lookup."""
    return re.split(r"(?<=[.!?])\s+|\n{2,}", latex)[:200]


def _latex_to_text(latex: str) -> str:
    """Best-effort conversion of LaTeX math to readable text."""
    t = re.sub(r"\\(?:frac|dfrac)\{([^}]+)\}\{([^}]+)\}", r"(\1)/(\2)", latex)
    t = re.sub(r"\\(?:sum|Sigma)", "∑", t)
    t = re.sub(r"\\(?:prod|Pi)", "∏", t)
    t = re.sub(r"\\int(?:egral)?", "∫", t)
    t = re.sub(r"\\(?:partial|nabla)", "∇", t)
    t = re.sub(r"\\(?:alpha|Alpha)", "α", t)
    t = re.sub(r"\\(?:beta|Beta)", "β", t)
    t = re.sub(r"\\(?:gamma|Gamma)", "γ/Γ", t)
    t = re.sub(r"\\(?:delta|Delta)", "δ/Δ", t)
    t = re.sub(r"\\(?:epsilon|varepsilon)", "ε", t)
    t = re.sub(r"\\(?:theta|Theta|vartheta)", "θ/Θ", t)
    t = re.sub(r"\\(?:lambda|Lambda)", "λ/Λ", t)
    t = re.sub(r"\\(?:mu)", "μ", t)
    t = re.sub(r"\\(?:sigma|Sigma)", "σ/Σ", t)
    t = re.sub(r"\\(?:tau)", "τ", t)
    t = re.sub(r"\\(?:phi|Phi|varphi)", "φ/Φ", t)
    t = re.sub(r"\\(?:psi|Psi)", "ψ/Ψ", t)
    t = re.sub(r"\\(?:omega|Omega)", "ω/Ω", t)
    t = re.sub(r"\\(?:infty)", "∞", t)
    t = re.sub(r"\\(?:leq|le)\b", "≤", t)
    t = re.sub(r"\\(?:geq|ge)\b", "≥", t)
    t = re.sub(r"\\(?:neq|ne)\b", "≠", t)
    t = re.sub(r"\\(?:approx)", "≈", t)
    t = re.sub(r"\\(?:cdot|times)", "×", t)
    t = re.sub(r"\\(?:in)\b", "∈", t)
    t = re.sub(r"\\(?:subset)", "⊂", t)
    t = re.sub(r"\\text\{([^}]+)\}", r"\1", t)
    t = re.sub(r"\\mathbf\{([^}]+)\}", r"\1", t)
    t = re.sub(r"\\mathit\{([^}]+)\}", r"\1", t)
    t = re.sub(r"\\mathrm\{([^}]+)\}", r"\1", t)
    t = re.sub(r"\\hat\{([^}]+)\}", r"\1̂", t)
    t = re.sub(r"\\vec\{([^}]+)\}", r"⃗\1", t)
    t = re.sub(r"\^(\{[^}]+\}|[^{])", r"^\1", t)   # keep superscripts readable
    t = re.sub(r"_(\{[^}]+\}|[^{])", r"_\1", t)
    t = re.sub(r"\\[a-zA-Z]+", "", t)               # strip remaining commands
    t = re.sub(r"[{}]", "", t)
    return " ".join(t.split())[:400]


# ---------------------------------------------------------------------------
# Backward-compat plain-text section splitter (used by demo/text path)
# ---------------------------------------------------------------------------

def split_into_sections(text: str) -> list[PaperSection]:
    if not text.strip():
        return []

    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [PaperSection(id="sec_text", title="Paper Text", type="body",
                             text=text.strip()[:10000], start_offset=0, end_offset=min(len(text), 10000))]

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
        sections.append(PaperSection(
            id=f"sec_{safe}", title=title.title(), type=safe,
            text=text[start:end].strip()[:10000],
            start_offset=start, end_offset=end,
        ))
    return sections


# ---------------------------------------------------------------------------
# Citation extraction + link enrichment
# ---------------------------------------------------------------------------

def extract_citations(text: str, sections: list[PaperSection]) -> list[Citation]:
    citations: dict[str, Citation] = {}

    for match in re.finditer(r"\[(\d{1,3}(?:\s*[,\-]\s*\d{1,3})*)\]", text):
        for num in _expand_nums(match.group(1)):
            cid = f"cit_{num}"
            if cid not in citations:
                citations[cid] = Citation(
                    id=cid, raw=f"[{num}]",
                    context_snippet=_snippet(text, match.start(), match.end()),
                )

    author_year_re = re.compile(r"([A-Z][A-Za-z\-]+(?:\s+et\s+al\.?)?\s*[,(]\s*\d{4}[),]?)")
    for match in author_year_re.finditer(text):
        raw = match.group(1).strip().rstrip(",)")
        year_m = re.search(r"(\d{4})", raw)
        slug = re.sub(r"\W+", "_", raw.lower())[:32]
        cid = f"cit_a_{slug}"
        if cid not in citations:
            citations[cid] = Citation(
                id=cid, raw=raw,
                year=int(year_m.group(1)) if year_m else None,
                context_snippet=_snippet(text, match.start(), match.end()),
            )

    _enrich_from_bibliography(text, citations)
    return list(citations.values())


def enrich_citations_with_links(citations: list[Citation], bib_text: str) -> None:
    """
    Mutate citations in-place: add .doi and .url fields from bibliography text.
    Also derives .arxiv_id when an arXiv reference is found.
    """
    for cit in citations:
        if cit.doi and cit.url:
            continue

        # Find the bibliography entry for this citation
        num = cit.id.removeprefix("cit_")
        if num.isdigit():
            pattern = re.compile(
                rf"\[{re.escape(num)}\]\s+(.+?)(?=\n\s*\[\d+\]|\Z)",
                re.DOTALL | re.MULTILINE,
            )
            m = pattern.search(bib_text)
            entry_text = m.group(1).replace("\n", " ") if m else ""
        else:
            # author-year citation: search for raw text
            entry_text = ""

        if not entry_text and cit.title:
            entry_text = cit.title

        # DOI
        doi_m = _DOI_RE.search(entry_text)
        if doi_m:
            doi = doi_m.group(1).rstrip(".")
            cit.doi = doi
            if not cit.url:
                cit.url = f"https://doi.org/{doi}"

        # arXiv
        arxiv_m = _ARXIV_REF_RE.search(entry_text)
        if arxiv_m:
            arxiv_id = arxiv_m.group(1)
            cit.arxiv_id = cit.arxiv_id or arxiv_id
            if not cit.url:
                cit.url = f"https://arxiv.org/abs/{arxiv_id}"

        # Semantic Scholar fallback URL
        if not cit.url and cit.semantic_scholar_id:
            cit.url = f"https://www.semanticscholar.org/paper/{cit.semantic_scholar_id}"


# ---------------------------------------------------------------------------
# Figure extraction (with vision description slot)
# ---------------------------------------------------------------------------

def extract_figures_from_pdf_bytes(
    pdf_bytes: bytes,
    sections: list[PaperSection],
    max_figures: int = 12,
) -> list[FigureExtract]:
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
            import fitz as _fitz
            rect = _fitz.Rect(bbox)
            if rect.width < 80 or rect.height < 60:
                continue
            try:
                mat = _fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat, clip=rect, colorspace=_fitz.csRGB)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()
            except Exception:
                continue
            caption = _find_caption_near_rect(page, rect)
            section_id = _page_to_section_id(page_num, total_pages, sections)
            figures.append(FigureExtract(
                caption=caption, image_b64=img_b64, page=page_num, section_id=section_id,
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
                rows = [[str(cell).strip() if cell else "" for cell in row]
                        for row in rows if any(cell for cell in row)]
            except Exception:
                rows = []
            img_b64 = ""
            try:
                import fitz as _fitz
                mat = _fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat, clip=tab.bbox, colorspace=_fitz.csRGB)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()
            except Exception:
                pass
            import fitz as _fitz
            caption = _find_caption_near_rect(page, _fitz.Rect(tab.bbox), look_above=True)
            section_id = _page_to_section_id(page_num, total_pages, sections)
            tables.append(TableExtract(
                caption=caption, rows=rows[:30], image_b64=img_b64, section_id=section_id,
            ))

    doc.close()
    return tables


# ---------------------------------------------------------------------------
# Attach visuals to their parent sections
# ---------------------------------------------------------------------------

def attach_visuals_to_sections(
    sections: list[PaperSection],
    figures: list[FigureExtract],
    tables: list[TableExtract],
    equations: list[EquationExtract] | None = None,
) -> None:
    sec_map = {s.id: s for s in sections}
    for fig in figures:
        if fig.section_id and fig.section_id in sec_map:
            sec_map[fig.section_id].figures.append(fig)
    for tab in tables:
        if tab.section_id and tab.section_id in sec_map:
            sec_map[tab.section_id].tables.append(tab)
    if equations:
        for eq in equations:
            if eq.section_id and eq.section_id in sec_map:
                sec_map[eq.section_id].equations.append(eq)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_caption_near_rect(page: Any, rect: Any, look_above: bool = False) -> str | None:
    try:
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
            if not low.startswith(("figure", "fig.", "fig ", "table", "tab.")):
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
        if not cit.title:
            title_m = re.search(r"[A-Z][^.]{10,100}\.", entry)
            if title_m:
                cit.title = title_m.group(0).rstrip(".").strip()[:160]
        if not cit.year:
            year_m = re.search(r"\b(19|20)\d{2}\b", entry)
            if year_m:
                cit.year = int(year_m.group(0))
        if not cit.authors:
            author_chunk = entry.split(".")[0] if "." in entry else ""
            if author_chunk:
                cit.authors = [a.strip() for a in author_chunk.split(",") if a.strip()][:4]
        # DOI + URL
        doi_m = _DOI_RE.search(entry)
        if doi_m and not cit.doi:
            doi = doi_m.group(1).rstrip(".")
            cit.doi = doi
            cit.url = cit.url or f"https://doi.org/{doi}"
        arxiv_m = _ARXIV_REF_RE.search(entry)
        if arxiv_m and not cit.arxiv_id:
            arxiv_id = arxiv_m.group(1)
            cit.arxiv_id = arxiv_id
            cit.url = cit.url or f"https://arxiv.org/abs/{arxiv_id}"


def _snippet(text: str, start: int, end: int, width: int = 160) -> str:
    return " ".join(text[max(0, start - width): min(len(text), end + width)].split())
