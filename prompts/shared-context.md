# Shared DeepPaper Context

We are building DeepPaper for a hackathon.

DeepPaper is a multi-agent research reading app. The user uploads or pastes an arXiv paper link. The system parses the paper, renders sections, makes citations clickable, finds related papers/code, critiques claims, and builds a live knowledge graph. The defining behavior: every agent acts relative to the MAIN PAPER context. References are not summarized generically; they are explained in terms of how they support, extend, contradict, or contextualize the main paper.

Hackathon MVP:

- Paper upload or arXiv URL input.
- Section parsing into Abstract, Introduction/Related Work, Methodology, Evaluation/Experiments, References/Bibliography.
- Clickable citations.
- Contextual summary for clicked citation.
- Code finder agent.
- Basic live knowledge graph visualization.
- Visible multi-agent event stream showing handoffs.
- Optional W&B Weave instrumentation.
- Upload parsing must work even if external APIs fail, using local graceful fallbacks.

Tech choices:

- Backend: Python FastAPI.
- Frontend: React + Vite + TypeScript.
- Graph: simple SVG or D3.
- Storage: in-memory session store plus optional JSON dump.
- Event stream: Server-Sent Events preferred; polling fallback is acceptable.
- Paper metadata: arXiv API and/or Semantic Scholar API.
- Code search: GitHub API with a local unavailable-search fallback.
- LLM calls: wrap behind a simple service so the app runs with deterministic fallback outputs if no API key is present.

Repository structure:

```txt
backend/
  app/
    main.py
    models.py
    store.py
    events.py
    agents/
    services/
frontend/
  src/
    components/
    App.tsx
    api.ts
    types.ts
prompts/
README.md
```

Shared core event types:

- session.created
- paper.loading
- paper.parsed
- citation.clicked
- citation.resolving
- citation.resolved
- agent.started
- agent.finished
- agent.failed
- node.update
- edge.update
- critique.finding
- paper.contradiction
- code.search.started
- repo.ready
- experiment.missing
- replication.queued
- metrics.discrepancy
- benchmark.suggested
- attack.found

Shared backend models:

- PaperSection: id, title, type, text, start_offset?, end_offset?
- Citation: id, raw, title?, authors?, year?, semantic_scholar_id?, arxiv_id?, context_snippet?, resolved_paper_id?
- Claim: id, text, section_id, confidence, evidence?
- Paper: id, title, authors, year?, abstract?, source_url?, arxiv_id?, semantic_scholar_id?, sections, citations, claims, is_main
- GraphNode: id, label, type, status, paper_id?, metadata
- GraphEdge: id, source, target, type, label, confidence?, evidence?
- AgentEvent: id, session_id, timestamp, type, agent?, status?, message, payload
- AgentFinding: id, agent, severity, title, body, related_paper_id?, related_section_id?, related_claim_id?

Integration rule:

Never break the public API used by other teammates. If you need to change a schema, add optional fields instead of renaming existing ones.

Demo reliability rule:

Every external API call must have a graceful fallback. Uploading a local paper should still produce readable sections, citation chips, agent events, and graph updates with no API keys.

Quality bar:

- Implement clean, typed, minimal code.
- Add useful comments only where logic is non-obvious.
- Include basic tests or at least a smoke script where practical.
- Keep UI fast and robust.
- Prioritize visible orchestration over deep research perfection.
