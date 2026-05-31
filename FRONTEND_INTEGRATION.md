# DeepPaper — Frontend Integration Guide

## Running the stack

Open **two terminal tabs** from the repo root:

```bash
# Terminal 1 — Backend (FastAPI + all 7 agents)
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend (React + Vite)
cd frontend
npm install   # first time only
npm run dev   # → http://localhost:5173
```

To see every agent's output printed in the terminal, run the demo script
in a **third tab** while both servers are up:

```bash
# Terminal 3 — agent output viewer
python demo_agents.py          # pretty-prints all 7 agents via HTTP
python demo_agents.py --inprocess  # no server needed, runs agents directly
```

---

## API contract — what the backend returns

### POST `/api/sessions`
```json
{ "session_id": "session_abc123", "created_at": "...", "graph": {...}, "events": [] }
```

### POST `/api/sessions/{sid}/papers/load`
Body: `{ "source_type": "demo" | "arxiv_url" | "pdf_text", "source": "" }`

Returns a `Paper` object:
```json
{
  "id": "paper_...",
  "title": "LoRA: Low-Rank Adaptation of Large Language Models",
  "authors": ["Edward J. Hu", "..."],
  "year": 2021,
  "abstract": "...",
  "arxiv_id": "2106.09685",
  "sections": [
    { "id": "sec_abstract", "title": "Abstract", "type": "abstract", "text": "..." }
  ],
  "citations": [
    {
      "id": "cit_adapter",
      "raw": "[1] Parameter-Efficient Transfer Learning for NLP",
      "title": "Parameter-Efficient Transfer Learning for NLP",
      "authors": ["..."],
      "year": 2019
    }
  ],
  "claims": [
    {
      "id": "claim_...",
      "text": "LoRA reduces trainable parameters by several orders of magnitude.",
      "confidence": 0.88,
      "evidence": ["LLM extraction"]
    }
  ],
  "is_main": true
}
```

### POST `/api/sessions/{sid}/citations/{cid}/click`
Fires the **full 7-agent chain** and returns everything in one response:

```json
{
  "citation": { ...Citation },
  "referenced_paper": { ...Paper },

  "summary": {
    "relationship": "baseline_for",
    "summary": "Adapter layers are the key baseline…",
    "why_it_matters_for_main_paper": "LoRA needs adapters as a baseline…",
    "supporting_evidence": ["Adapter modules are trainable bottleneck layers."],
    "possible_contradiction": "The latency comparison depends on implementation details…"
  },

  "code": {
    "repo": {
      "full_name": "microsoft/LoRA",
      "html_url": "https://github.com/microsoft/LoRA",
      "description": "Reference implementation for LoRA…",
      "stargazers_count": 0
    },
    "paper_claim_connection": "The repo implements LoRA's core method.",
    "key_files": [
      { "path": "loralib/layers.py", "why_relevant": "Core LoRA layer implementation." }
    ],
    "implementation_risks": ["Benchmark scripts may not exactly match the paper."],
    "code_gaps": [],
    "handoff_to_replication": {
      "entrypoint_guess": "examples/",
      "setup_guess": "pip install -r requirements.txt && pip install -e .",
      "minimal_run_plan": ["Run the smallest published task configuration."]
    }
  },

  "replication": {
    "claim_under_test": "LoRA reaches adapter-level quality without adapter inference latency.",
    "expected_metric": "validation accuracy plus measured tokens/sec",
    "minimal_reproduction_steps": ["Install the reference repo…", "Run the smallest LoRA task…"],
    "environment": "Local demo dry run.",
    "scorecard": {
      "code_available": true,
      "data_available": null,
      "compute_feasible": true,
      "expected_time": "demo dry run only",
      "confidence": 0.62
    },
    "discrepancies": [],
    "risks": ["Dataset preprocessing differences", "Unmatched serving stack"]
  },

  "adversarial": {
    "tests": [
      {
        "name": "Rank sensitivity stress test",
        "severity": "medium",
        "description": "Vary rank r across {1,2,4,8,16,32}…",
        "expected_outcome": "Performance should degrade gracefully…"
      }
    ]
  },

  "graph": { "nodes": [...], "edges": [...] },
  "events": [...],
  "findings": [
    {
      "id": "finding_...",
      "agent": "Critique",
      "severity": "medium",
      "title": "Latency claim needs matched serving benchmark",
      "body": "LoRA's no-latency claim is plausible after merge, but…",
      "related_paper_id": "paper_..."
    }
  ]
}
```

### POST `/api/sessions/{sid}/agents/{agent}/run`
Runs a **single agent** on demand. Body: `{ "paper_id": "...", "section_id": "..." }`

Agent names: `critique` · `code` · `replication` · `evaluation` · `adversarial` · `reference`

Returns: `{ "agent": "critique", "output": {...}, "events": [...], "findings": [...], "graph": {...} }`

### GET `/api/sessions/{sid}/events/stream`
Server-Sent Events stream — one JSON object per event line.
Each event:
```json
{
  "id": "evt_...",
  "type": "critique.finding",
  "agent": "Critique",
  "status": "medium",
  "message": "Latency claim needs matched serving benchmark",
  "payload": { ...finding }
}
```

Key event `type` values to listen for in the UI:

| `type` | When | Payload |
|---|---|---|
| `paper.parsed` | Parser done | `{ paper_id, sections, citations }` |
| `citation.resolved` | Reference done | `{ citation, summary }` |
| `critique.finding` | Each critique finding | `AgentFinding` |
| `repo.ready` | Code agent done | `{ repo, key_files }` |
| `replication.queued` | Replication done | full replication dict |
| `node.update` | Graph node added | `GraphNode` |
| `edge.update` | Graph edge added | `GraphEdge` |
| `agent.started` / `agent.finished` | Agent lifecycle | `{ agent, status }` |
| `paper.contradiction` | Reference found conflict | `{ citation_id, note }` |

---

## Key things for the frontend team to wire up

### 1. Severity colours for findings
```
high   → red   (#ef4444)
medium → amber (#f59e0b)
low    → green (#22c55e)
```

### 2. Citation click response — where everything lives
```
response.summary           → Reference Agent card
response.code.repo         → Code Agent card (github link, stars)
response.code.key_files    → collapsible file list
response.code.code_gaps    → warning list
response.replication.scorecard   → checklist with tick/cross
response.replication.minimal_reproduction_steps → numbered list
response.adversarial.tests → stress-test cards with severity badge
response.findings          → findings panel (all agents combined)
response.graph             → update graph state
```

### 3. SSE stream (already wired in `api.ts`)
The `subscribeEvents` function in [frontend/src/api.ts](frontend/src/api.ts) is already
set up. Each incoming event has `agent`, `status`, `message`, and `payload`.
Use `status === "running"` to show a spinner on the agent card and
`status === "done"` to hide it.

### 4. Running individual agents
```ts
// Trigger critique agent on a specific section:
await runAgent(sessionId, "critique", { paper_id: paper.id, section_id: section.id })

// Trigger evaluation agent:
await runAgent(sessionId, "evaluation", { paper_id: paper.id })

// Trigger adversarial agent:
await runAgent(sessionId, "adversarial", { paper_id: paper.id })
```

### 5. Graph nodes
Two node types come back:
- `type: "paper"` — main paper or referenced paper; `status: "main"` or `"referenced"`
- `type: "code"` — GitHub repo; `status: "code-found"`

Edges:
- `type: "cites"` — paper → paper citation
- `type: "implements"` — paper → code repo

---

## Demo run (no API keys needed)
```bash
python demo_agents.py --inprocess
```
All agents run with fixture data — no Groq / W&B keys required.
Set `GROQ_API_KEY` in `.env` for live LLM responses.
