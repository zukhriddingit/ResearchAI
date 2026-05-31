# DeepPaper Team Prompts

Each teammate should paste `shared-context.md` first, then paste their lane-specific prompt.

- Team 1: `team-1-backend-orchestrator.md`
- Team 2: `team-2-ingestion-reference-critique.md`
- Team 3: `team-3-frontend-ux.md`
- Team 4: `team-4-harness-weave-demo.md`

Integration order:

1. Team 1 keeps `/health`, `/sessions`, upload, arXiv load, and citation click stable.
2. Team 3 builds UI against Team 1's upload and session endpoints immediately.
3. Team 2 improves Parser, Reference, and Critique behind the same API.
4. Team 4 adds Code, Replication, Evaluation, Adversarial, Weave, and demo polish.
5. Everyone tests one path repeatedly: create session, upload a paper, click a citation, watch graph and event feed update.
