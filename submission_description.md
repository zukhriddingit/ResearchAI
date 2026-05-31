# DeepPaper Submission Description

## Summary

DeepPaper is a multi-agent research reading app that turns a single paper into a live research session. It parses the main paper, resolves citations in context, critiques claims, finds implementation code, queues replication work, and updates a knowledge graph as agents hand tasks to one another.

## Problem

Reading research papers is slow because each citation, baseline, claim, and implementation detail requires a separate search. Generic paper summarizers lose the most important context: why a referenced paper matters for the paper currently being read.

## What It Does

- Loads a demo LoRA paper or arXiv URL.
- Parses sections, citations, and claims.
- Makes citations clickable.
- Resolves references relative to the main paper.
- Builds a graph of papers, code repos, and typed relationships.
- Emits visible agent handoffs in a live event feed.
- Finds code and queues a truthful replication dry run.
- Suggests benchmarks and adversarial stress tests.

## How It Is Built

- Backend: FastAPI, Pydantic, in-memory session store, Server-Sent Events.
- Frontend: React, Vite, TypeScript, SVG knowledge graph.
- Agents: Parser, Reference, Critique, Code, Replication, Evaluation, Adversarial.
- Handoff protocol: typed append-only events such as `paper.parsed`, `citation.resolved`, `experiment.missing`, `repo.ready`, `replication.queued`, `benchmark.suggested`, `attack.found`, `node.update`, and `edge.update`.
- Harness: Code searches implementation candidates, Replication returns a dry-run scorecard, Evaluation proposes missing experiments, and Adversarial converts claims into stress tests.
- Reliability: fixture-first LoRA path works without API keys.

## Sponsor Tools

- W&B Weave: optional trace hooks for agent runs and events. It is a no-op unless both `WEAVE_PROJECT` and `WANDB_API_KEY` are configured.
- Anthropic API: optional LLM wrapper for structured completions.
- arXiv: optional metadata/PDF retrieval.
- Semantic Scholar: optional paper/reference resolution.
- GitHub API: optional implementation repository search with deterministic fixture fallback.

## Demo Notes

The current replication agent is intentionally labeled as a dry-run scorecard. It does not execute arbitrary external research repos during the hackathon demo; it reports repo availability, metric readiness, blockers, and the next human verification step.
