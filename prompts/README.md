# DeepPaper Team Prompts

Each teammate should paste `shared-context.md` first, then paste their lane-specific prompt.

- Team 1: `team-1-backend-orchestrator.md`
- Team 2: `team-2-ingestion-reference-critique.md`
- Team 3: `team-3-frontend-ux.md`
- Team 4: `team-4-harness-weave-demo.md`

Integration order:

1. Team 1 keeps `/health`, `/sessions`, demo load, and fixture citation click stable.
2. Team 3 builds UI against Team 1's fixture endpoints immediately.
3. Team 2 improves Parser, Reference, and Critique behind the same API.
4. Team 4 adds Code, Replication, Evaluation, Adversarial, Weave, and demo polish.
5. Everyone tests one demo path repeatedly: create session, load LoRA demo, click adapter citation, watch graph and event feed update.

