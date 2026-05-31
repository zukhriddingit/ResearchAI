# Team 1 Prompt: Backend Orchestrator, API, Event Bus, Shared Models

You are Coding Agent #1 for DeepPaper. Your job is to build and protect the backend spine: FastAPI app, shared data models, session store, event bus, APIs, and orchestration hooks. Other teammates depend on your contracts.

You own:

- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/store.py`
- `backend/app/events.py`
- `backend/app/agents/base.py`
- `backend/app/demo/lora_fixture.json`
- `backend/requirements.txt`
- backend README sections

Primary goal:

Create a working FastAPI backend that can drive the whole demo even before real agents are implemented.

Implement or maintain these endpoints:

- `GET /health`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/events`
- `GET /api/sessions/{session_id}/events/stream`
- `POST /api/sessions/{session_id}/papers/load`
- `POST /api/sessions/{session_id}/citations/{citation_id}/click`
- `POST /api/sessions/{session_id}/agents/{agent_name}/run`

Event bus requirements:

- Append-only in-memory log per session.
- Every event includes id, session_id, timestamp, type, agent, status, message, payload.
- Keep helpers for create_session, get_session, add_paper, add_node, add_edge, add_finding.

Orchestration requirements:

- On paper load, emit `paper.loading`, `agent.started`, `paper.parsed`, `node.update`, `agent.finished`.
- On citation click, call Reference Agent, add node/edge, emit `citation.resolved`, then trigger Critique and Code stubs.
- On critique missing experiment, let Code Agent and Replication Agent react.
- Use deterministic fixture outputs when a real agent is missing.

Acceptance checks:

- `uvicorn app.main:app --reload` starts from `backend/`.
- `GET /health` returns ok.
- Demo load returns paper, graph, and events.
- Clicking `cit_adapter` creates a referenced paper node and edge.
- `agents/critique/run` returns at least one finding.

Do not add database complexity or break frontend API assumptions.

