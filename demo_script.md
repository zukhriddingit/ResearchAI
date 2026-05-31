# DeepPaper Demo Script

Target length: under 2 minutes.

1. "DeepPaper turns one paper into a coordinated research session. The main paper stays as shared context for every agent."
2. Click `LoRA Demo`.
3. "The Parser Agent creates structured sections, citations, claims, and the initial graph node."
4. Click citation `[1] Parameter-Efficient Transfer Learning for NLP`.
5. "The Reference Agent resolves this citation relative to LoRA, not as a generic summary."
6. Point to the graph.
7. "The graph now has a typed baseline edge from LoRA to Adapters."
8. Point to event feed.
9. "Critique flags a missing matched latency benchmark, Code finds the LoRA repo, and Replication queues a dry-run scorecard."
10. "The replication step is intentionally a dry run. It tells us what can be verified, what is blocked, and what a human should check before running external code."
11. Run Evaluation.
12. "Evaluation suggests the missing benchmarks: matched latency, rank sensitivity, memory, throughput, and OOD coverage."
13. Run Adversarial.
14. "Adversarial turns those claims into stress tests, including rank sensitivity, baseline omissions, and compute edge cases."
15. "This is the product: agents hand work to each other and update shared research memory."
