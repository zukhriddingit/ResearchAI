# DeepPaper

Read one paper. Understand the whole field.

DeepPaper is a multi-agent research reading app for the Multi-Agent Orchestration Build Day hackathon. The app loads a paper, parses sections and citations, explains references relative to the main paper, critiques claims, finds implementation code, queues replication work, and grows a live knowledge graph from the reading session.

## What Works In This Starter

- FastAPI backend with typed Pydantic models.
- In-memory sessions, graph state, findings, and agent event log.
- Server-Sent Events endpoint with frontend polling fallback.
- PDF/text upload with optional original-file storage in Cloudinary.
- React/Vite frontend with paper reader, citation chips, graph panel, and agent feed.
- Harness agents for code search, dry-run replication scoring, benchmark suggestions, and adversarial stress tests.
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

The core protocol is an append-only event stream. Agents emit handoffs such as `paper.parsed`, `citation.resolved`, `critique.finding`, `experiment.missing`, `code.search.started`, `repo.ready`, `replication.queued`, `benchmark.suggested`, `attack.found`, `node.update`, and `edge.update`.

The main demo chain is:

```txt
Reference resolves citation
  -> Critique flags an experiment gap
  -> Code finds an implementation repo
  -> Replication queues a dry-run scorecard
  -> Evaluation suggests benchmarks
  -> Adversarial proposes stress tests
  -> Graph receives paper/code nodes and typed edges
```

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

Team 3 frontend details live in `frontend/README.md`.

If your backend runs somewhere else:

```bash
VITE_API_URL=http://localhost:8000 npm run dev
```

## Deploy Frontend To GitHub Pages

The React frontend is deployed by `.github/workflows/deploy-pages.yml` on every push to `main`.

GitHub Pages hosts only the static frontend. The FastAPI backend still needs to run locally or be deployed separately. If the backend is deployed publicly, set a repository variable named `VITE_API_URL` to the backend origin, for example:

```txt
https://your-backend.example.com
```

For local demos from the Pages site, leave `VITE_API_URL` unset and run the backend at `http://localhost:8000`. The backend allows the GitHub Pages origin by default; for another frontend domain, set:

```txt
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,https://zukhriddingit.github.io,https://your-domain.example.com
```

## Deploy Backend To Hugging Face Spaces

Create a Docker Space with:

```txt
SDK: Docker
Hardware: CPU Basic
Storage bucket: off
Dev mode: off
```

The root `Dockerfile` runs the FastAPI backend on port `7860`, which is the required Hugging Face Spaces app port.

Set Space secrets for the backend API keys:

```txt
WANDB_API_KEY
WANDB_INFERENCE_PROJECT
WEAVE_PROJECT
SEMANTIC_SCHOLAR_API_KEY
GITHUB_TOKEN
CLOUDINARY_CLOUD_NAME
CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET
```

Set this Space variable so browser calls from GitHub Pages are accepted:

```txt
FRONTEND_ORIGINS=https://zukhriddingit.github.io,http://localhost:5173,http://127.0.0.1:5173
```

After the Space is deployed, set the GitHub repository variable `VITE_API_URL` to the Space URL, for example:

```txt
https://zukhriddinai-researchai.hf.space
```

## Demo Flow

1. Open the frontend.
2. Click `Upload Paper` and select a PDF or text paper.
3. Confirm the paper sections render in the center.
4. Click a citation chip or inline citation.
5. Watch Reference, Critique, Code, and Replication events appear.
6. Confirm the graph adds a reference paper node and typed citation edge.
7. Run Evaluation or Adversarial manually from the agent panel.

## Optional Environment

Copy `backend/.env.example` to `backend/.env` and fill in your values:

```bash
cd backend
cp .env.example .env
```

For W&B, the important fields are:

```bash
WANDB_API_KEY=your_wandb_api_key_here
WANDB_INFERENCE_PROJECT=your-team/deeppaper
WEAVE_PROJECT=your-team/deeppaper
```

Full optional config:

```bash
SEMANTIC_SCHOLAR_API_KEY=
GITHUB_TOKEN=
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
CLOUDINARY_UPLOAD_FOLDER=researchai/papers
WANDB_API_KEY=
WANDB_INFERENCE_PROJECT=your-team/researchai
WANDB_INFERENCE_BASE_URL=https://api.inference.wandb.ai/v1
WANDB_INFERENCE_MODEL=google/gemma-4-31B-it
WANDB_INFERENCE_REASONING_MODEL=deepseek-ai/DeepSeek-V4-Flash
WANDB_INFERENCE_ENABLE_THINKING=true
WEAVE_PROJECT=your-team/researchai
ANTHROPIC_API_KEY=
```

The app must still run without these keys. Upload parsing works without Cloudinary; Cloudinary only stores the original uploaded file when the `CLOUDINARY_*` variables are present.

When `WANDB_API_KEY` and `WANDB_INFERENCE_PROJECT` are set, DeepPaper uses W&B Serverless Inference through its OpenAI-compatible API. When `WEAVE_PROJECT` is set, agent calls and model calls are traced in W&B Weave. Without those variables, the app falls back to deterministic fixture outputs.

The default W&B setup uses Gemma 4 31B for normal completions and DeepSeek V4-Flash for reasoning-heavy agent calls. Set `WANDB_INFERENCE_ENABLE_THINKING=false` if you want lower token use on models that support controllable reasoning.

## Team Workflow

Each teammate should paste `prompts/shared-context.md` first, then their lane-specific prompt:

- Team 1: backend orchestrator and API contracts.
- Team 2: ingestion, parser, reference, critique.
- Team 3: frontend UX and graph.
- Team 4: code/replication/evaluation/adversarial harness, Weave, demo polish.

See `prompts/README.md` for integration order.

## Sponsor Tool Usage

- W&B Weave: optional tracing hooks in `backend/app/services/weave_tracing.py`.
- W&B Serverless Inference: primary model provider in `backend/app/services/llm.py`.
- Anthropic API: optional fallback provider in `backend/app/services/llm.py`.
- Cloudinary: optional original PDF/text storage under `CLOUDINARY_UPLOAD_FOLDER`.
- arXiv: optional paper metadata and PDF fetch.
- Semantic Scholar: optional citation/reference resolution.
- GitHub API: optional code repository search with a local unavailable-search fallback.

## Known Limits

- Persistence is in memory.
- Uploaded papers are parsed immediately, but structured session data is still in memory.
- Replication is a local dry-run scorecard, not arbitrary repo execution.
- Citation extraction is heuristic until Team 2 upgrades it.
- Code search returns an unavailable-search placeholder when GitHub is unavailable or not configured.

## Hackathon Reminder

Prize eligibility requires a public GitHub repository, in-person demo, and submission through the AGI House platform. The final submission should include a demo video under 2 minutes and a project description that lists architecture, orchestration protocol, agent frameworks/tools, and sponsor tools used.
