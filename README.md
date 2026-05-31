# DeepPaper

Read one paper. Understand the whole field.

DeepPaper is a multi-agent research reading app for the Multi-Agent Orchestration Build Day hackathon. The app loads a paper, parses sections and citations, explains references relative to the main paper, critiques claims, finds implementation code, queues replication work, and grows a live knowledge graph from the reading session.

## What Works In This Starter

- FastAPI backend with typed Pydantic models.
- In-memory sessions, graph state, findings, and agent event log.
- Server-Sent Events endpoint with frontend polling fallback.
- Deterministic LoRA demo fixture that works with no API keys.
- React/Vite frontend with paper reader, citation chips, graph panel, and agent feed.
- Teammate prompt files under `prompts/`.
- Optional integration hooks for arXiv, Semantic Scholar, GitHub, Anthropic, and W&B Weave.

## Architecture

```txt
frontend/ React + TypeScript
  UploadBar -> PaperViewer -> CitationPopover
  KnowledgeGraph
  AgentPanel

backend/ FastAPI
  main.py        API and orchestration
  models.py      shared contracts
  store.py       in-memory sessions
  events.py      event log and SSE
  agents/        parser, reference, critique, code, replication, evaluation, adversarial
  services/      arXiv, Semantic Scholar, GitHub, PDF parsing, LLM, Weave
```

The core protocol is an append-only event stream. Agents emit handoffs such as `paper.parsed`, `citation.resolved`, `critique.finding`, `experiment.missing`, `repo.ready`, `replication.queued`, `benchmark.suggested`, `attack.found`, `node.update`, and `edge.update`.

## Run Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend URL: `http://localhost:8000`

## Run Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`

If your backend runs somewhere else:

```bash
VITE_API_URL=http://localhost:8000 npm run dev
```

## Demo Flow

1. Open the frontend.
2. Click `LoRA Demo`.
3. Confirm the paper sections render in the center.
4. Click the Adapter citation `[1]`.
5. Watch Reference, Critique, Code, and Replication events appear.
6. Confirm the graph adds a reference paper node, code repo node, and typed edges.
7. Run Evaluation or Adversarial manually from the agent panel.

## Optional Environment

Copy `.env.example` to `backend/.env` or export these variables in your shell:

```bash
SEMANTIC_SCHOLAR_API_KEY=
GITHUB_TOKEN=
ANTHROPIC_API_KEY=
WEAVE_PROJECT=deeppaper
WANDB_API_KEY=
```

The demo must still run without these keys.

## Team Workflow

Each teammate should paste `prompts/shared-context.md` first, then their lane-specific prompt:

- Team 1: backend orchestrator and API contracts.
- Team 2: ingestion, parser, reference, critique.
- Team 3: frontend UX and graph.
- Team 4: code/replication/evaluation/adversarial harness, Weave, demo polish.

See `prompts/README.md` for integration order.

## Sponsor Tool Usage

- W&B Weave: optional tracing hooks in `backend/app/services/weave_tracing.py`.
- Anthropic API: optional LLM wrapper in `backend/app/services/llm.py`.
- arXiv: optional paper metadata and PDF fetch.
- Semantic Scholar: optional citation/reference resolution.
- GitHub API: optional code repository search.

## Known Limits

- Persistence is in memory.
- The LoRA flow is fixture-first for demo reliability.
- Replication is a local dry-run scorecard, not arbitrary repo execution.
- Citation extraction is heuristic until Team 2 upgrades it.

## Hackathon Reminder

Prize eligibility requires a public GitHub repository, in-person demo, and submission through the AGI House platform. The final submission should include a demo video under 2 minutes and a project description that lists architecture, orchestration protocol, agent frameworks/tools, and sponsor tools used.

