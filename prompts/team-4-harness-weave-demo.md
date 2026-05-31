# Team 4 Prompt: Harness Agents, Weave, Demo Polish

You are Coding Agent #4 for DeepPaper. Your job is to build the sophisticated harness layer: Code Agent, Replication Agent, Evaluation Agent, Adversarial Agent, W&B Weave trace hooks, README/demo script, and submission polish.

You own:

- `backend/app/services/github_client.py`
- `backend/app/services/paperswithcode_client.py` optional
- `backend/app/services/sandbox.py` optional
- `backend/app/agents/code_agent.py`
- `backend/app/agents/replication_agent.py`
- `backend/app/agents/evaluation_agent.py`
- `backend/app/agents/adversarial_agent.py`
- `backend/app/services/weave_tracing.py`
- `README.md`
- `demo_script.md`
- `submission_description.md`

Primary goal:

Make the app clearly show multiple agents handing work to each other:

Reference finds relevant paper -> Critique flags issue -> Code finds repo -> Replication queues run -> Evaluation suggests benchmark -> Adversarial proposes stress test -> Graph updates.

Implementation targets:

- GitHub client searches repos by paper title, arXiv ID, method terms, and author/method terms.
- Code Agent emits `code.search.started` and `repo.ready`, returns repo, key files, claim connection, risks, and replication handoff.
- Replication Agent emits `replication.queued` and returns a truthful scorecard. Use harmless dry runs only unless real sandboxing is ready.
- Evaluation Agent emits `benchmark.suggested` and `experiment.missing` for evaluation gaps.
- Adversarial Agent emits `attack.found` for rank sensitivity, OOD/code tasks, compute/memory edge cases, and baseline omissions.
- Weave tracing is a no-op unless `WEAVE_PROJECT` and `WANDB_API_KEY` are configured.

README requirements:

- Project name and tagline.
- Problem and what it does.
- Architecture and agent handoff protocol.
- Tech stack.
- Sponsor tools used, especially W&B Weave for tracing.
- Backend and frontend run commands.
- Demo flow.
- Known limitations and future work.

Acceptance checks:

- Code Agent returns `repo.ready` with an unavailable-search placeholder if GitHub fails.
- Replication Agent returns scorecard and emits `replication.queued`.
- Evaluation Agent emits `benchmark.suggested`.
- Adversarial Agent emits `attack.found`.
- Weave no-op path works.
- Submission description is ready to paste.

Do not promise real replication if only a dry run is implemented.
