# DeepPaper Frontend

React/Vite/TypeScript UI for the DeepPaper hackathon demo.

## Run

```bash
npm install
npm run dev
```

Default URL: `http://127.0.0.1:5173`

The frontend expects the backend at `http://localhost:8000` unless `VITE_API_URL` is set:

```bash
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

## Team 3 Scope

- `src/App.tsx`: session lifecycle, loading state, event subscription, API orchestration.
- `src/api.ts`: typed backend API client and SSE subscription helper.
- `src/types.ts`: frontend mirror of backend Pydantic models.
- `src/components/UploadBar.tsx`: app title, arXiv URL input, load actions.
- `src/components/UploadBar.tsx`: also includes PDF/text upload.
- `src/components/PaperViewer.tsx`: section reader, inline citations, citation chips, agent action buttons.
- `src/components/CitationPopover.tsx`: citation resolving state and contextual reference summary.
- `src/components/KnowledgeGraph.tsx`: radial SVG graph, clickable nodes, metadata detail panel.
- `src/components/AgentPanel.tsx`: agent cards, event feed, handoff rail, findings.
- `src/components/FindingCard.tsx`: reusable finding display.

## Demo Checklist

1. Start backend and frontend.
2. Click `LoRA Demo` or upload a PDF/text paper.
3. Confirm the main paper sections appear.
4. Click citation `[1]` inline or in the citation chip row.
5. Confirm the citation detail shows a resolving state, then a contextual summary.
6. Confirm the graph adds the referenced paper and code repo.
7. Confirm the agent panel shows handoffs such as `Reference -> Graph` and `Critique -> Code`.
8. Run `Evaluation` or `Adversarial` from the agent panel.
