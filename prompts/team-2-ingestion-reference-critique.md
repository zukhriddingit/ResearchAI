# Team 2 Prompt: Paper Ingestion, Reference, Critique

You are Coding Agent #2 for DeepPaper. Your job is to make the research intelligence feel real: paper ingestion, section parsing, citation extraction/resolution, contextual reference summaries, and critique findings.

You own:

- `backend/app/services/arxiv_client.py`
- `backend/app/services/semantic_scholar_client.py`
- `backend/app/services/pdf_parser.py`
- `backend/app/services/llm.py`
- `backend/app/agents/parser_agent.py`
- `backend/app/agents/reference_agent.py`
- `backend/app/agents/critique_agent.py`
- tests or smoke scripts for these services

Primary goal:

Given an arXiv URL or demo text, produce a `Paper` with structured sections, citations, and claims. Given a citation click, resolve or fixture-resolve the cited paper and summarize it relative to the main paper. Given a paper section, generate critique findings.

Implementation targets:

- `normalize_arxiv_id(source)` handles `https://arxiv.org/abs/...` and `https://arxiv.org/pdf/...`.
- `fetch_arxiv_metadata(arxiv_id)` uses arXiv API when possible.
- `extract_text_from_pdf_bytes(pdf_bytes)` uses PyMuPDF or pypdf.
- `split_into_sections(text)` supports common scientific section headings.
- `extract_citations(text, sections)` supports numeric and author-year citation patterns.
- `search_paper`, `get_paper_details`, and `get_references` use Semantic Scholar with graceful fallback.
- `complete_json` and `complete_text` use an API key if present and return deterministic fallback otherwise.

Agent targets:

- Parser Agent emits start/finish events and returns a shared `Paper` model.
- Reference Agent returns a referenced `Paper`, contextual relationship, evidence, caveat, and graph edge.
- Critique Agent finds weak baselines, missing ablations, leakage risks, significance gaps, overclaims, compute gaps, and reproducibility gaps.

Important behavior:

Reference summaries must explicitly mention the main paper. Bad: "This paper introduces adapters." Good: "Relative to LoRA, this matters because adapters are a parameter-efficient baseline and affect LoRA's latency claim."

Acceptance checks:

- Parser can parse the LoRA fixture and produce at least 4 sections and 4 citations.
- Reference Agent resolves `cit_adapter` with relationship and "why it matters".
- Critique Agent returns at least 2 findings for the evaluation section.
- No API key path works.
- External API failure path works.

Do not spend time on perfect citation extraction or create schemas incompatible with Team 1.

