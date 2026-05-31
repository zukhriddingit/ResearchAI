# Team 3 Prompt: Frontend UX, Paper Viewer, Agent Panel, Knowledge Graph

You are Coding Agent #3 for DeepPaper. Your job is to make the product feel alive. Build the React/Vite/TypeScript frontend: upload bar, paper viewer, clickable citations, live agent panel, and knowledge graph.

You own:

- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/types.ts`
- `frontend/src/components/UploadBar.tsx`
- `frontend/src/components/PaperViewer.tsx`
- `frontend/src/components/CitationPopover.tsx`
- `frontend/src/components/KnowledgeGraph.tsx`
- `frontend/src/components/AgentPanel.tsx`
- `frontend/package.json`
- frontend README sections

Primary goal:

Make the demo visually obvious:

- Left: graph.
- Center: paper.
- Right: agents talking to each other.

The user should be able to load a demo paper, click a citation, watch agent events stream in, and see a new graph node/edge appear.

API client requirements:

- `createSession()`
- `loadPaper(sessionId, sourceType, source)`
- `getSession(sessionId)`
- `getEvents(sessionId)`
- `clickCitation(sessionId, citationId)`
- `runAgent(sessionId, agentName, payload)`
- `subscribeEvents(sessionId, onEvent)` using SSE if available and polling fallback if not.

UI requirements:

- Top bar with DeepPaper name, arXiv URL input, Load Paper, and LoRA Demo.
- Paper viewer renders sections, citation chips, and section actions.
- Knowledge graph updates from backend graph state.
- Agent panel displays Parser, Reference, Critique, Code, Replication, Evaluation, Adversarial, event feed, and findings.
- Buttons for Critique, Code, Replication, Evaluation, and Adversarial call the backend without crashing.

Acceptance checks:

- `npm install && npm run dev` starts.
- Load LoRA Demo works.
- Paper sections and citation chips appear.
- Clicking a citation updates events and graph.
- Agent cards change state when events arrive.

Do not build auth, PDF rendering, or hardcoded-only UI if the backend is working.

