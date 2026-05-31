#!/usr/bin/env python3
"""
DeepPaper — terminal demo
Runs the full 7-agent pipeline against the LoRA demo fixture and prints
every agent's output with colour-coded severity so you can judge response quality.

Usage (from repo root, with backend running OR without — pure in-process mode):
    python demo_agents.py                 # calls http://localhost:8000 (servers must be up)
    python demo_agents.py --inprocess     # runs agents directly, no server needed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
import urllib.request
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
MAGENTA= "\033[95m"
WHITE  = "\033[97m"

SEV_COLOR = {"high": RED, "medium": YELLOW, "low": GREEN}
AGENT_COLOR = {
    "Parser": CYAN, "Reference": BLUE, "Critique": YELLOW,
    "Code": MAGENTA, "Replication": GREEN, "Evaluation": BLUE, "Adversarial": RED,
}

def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def header(agent: str, subtitle: str = "") -> None:
    color = AGENT_COLOR.get(agent, WHITE)
    bar = "─" * 70
    print(f"\n{_c(color, bar)}")
    print(f"{_c(BOLD + color, f'  {agent.upper()} AGENT')}{_c(DIM, f'  {subtitle}')}")
    print(f"{_c(color, bar)}")

def section_line(label: str, value: str, indent: int = 2) -> None:
    pad = " " * indent
    print(f"{pad}{_c(BOLD, label + ':'):30s} {value}")

def bullet(items: list[str], indent: int = 4, color: str = "") -> None:
    for item in items:
        line = textwrap.fill(item, width=90, subsequent_indent=" " * (indent + 2))
        print(f"{' ' * indent}{_c(color, '•')} {line}")

def finding_block(f: dict, idx: int) -> None:
    sev = f.get("severity", "low")
    color = SEV_COLOR.get(sev, WHITE)
    title = f.get("title", "Untitled")
    body  = f.get("body", "")
    print(f"\n  {_c(color + BOLD, f'[{sev.upper()}]')} {_c(BOLD, title)}")
    for line in textwrap.wrap(body, width=88, initial_indent="    ", subsequent_indent="    "):
        print(line)

# ── HTTP helpers ───────────────────────────────────────────────────────────────

BASE = "http://localhost:8000"

def _post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.load(r)

# ── Via-HTTP mode ──────────────────────────────────────────────────────────────

def run_via_http() -> None:
    print(f"\n{_c(BOLD + CYAN, '═' * 70)}")
    print(f"{_c(BOLD + CYAN, '  DeepPaper — Full 7-Agent Pipeline Demo (HTTP mode)')}")
    print(f"{_c(BOLD + CYAN, '═' * 70)}")

    # Health check
    try:
        _get("/health")
        print(f"\n{_c(GREEN, '✓')} Backend healthy at {BASE}")
    except Exception as exc:
        print(f"\n{_c(RED, '✗')} Backend not reachable: {exc}")
        print(f"  Start it with:  {_c(DIM, 'cd backend && uvicorn app.main:app --reload')}")
        sys.exit(1)

    # 1. Session
    s = _post("/api/sessions")
    sid = s["session_id"]
    print(f"{_c(GREEN, '✓')} Session: {_c(DIM, sid)}")

    # 2. Parser
    print(f"\n{_c(DIM, '  Loading demo paper …')}", end="", flush=True)
    pr = _post(f"/api/sessions/{sid}/papers/load", {"source_type": "demo", "source": ""})
    paper = pr["paper"]
    print(f"\r", end="")
    header("Parser", "arXiv extraction · section splitting · claim extraction")
    section_line("Title",   paper["title"])
    section_line("Authors", ", ".join(paper["authors"][:4]))
    section_line("Year",    str(paper.get("year") or "N/A"))
    section_line("Sections", str(len(paper["sections"])))
    section_line("Citations", str(len(paper["citations"])))
    section_line("Claims",   str(len(paper["claims"])))
    if paper["claims"]:
        print(f"\n  {_c(BOLD, 'Extracted claims:')}")
        for c in paper["claims"]:
            conf = f"{c['confidence']:.0%}"
            line = textwrap.fill(c["text"], width=85, subsequent_indent="       ")
            print(f"    {_c(DIM, conf)}  {line}")
    if paper["sections"]:
        print(f"\n  {_c(BOLD, 'Sections:')}")
        for s_item in paper["sections"]:
            snippet = s_item["text"][:120].replace("\n", " ")
            print(f"    {_c(CYAN, s_item['title'][:30]):35s} {_c(DIM, snippet + '…')}")

    # 3. Citation click → all downstream agents
    cit = paper["citations"][0]
    cit_label = cit["raw"][:60]
    print(f"\n{_c(DIM, f'  Clicking citation [{cit_label}] — fires all downstream agents …')}", flush=True)
    cr = _post(f"/api/sessions/{sid}/citations/{cit['id']}/click")

    # Reference
    header("Reference", "citation resolution · relationship · contradiction detection")
    ref = cr["referenced_paper"]
    summary = cr["summary"]
    section_line("Referenced paper", ref["title"][:80])
    section_line("Relationship",     summary.get("relationship", "")[:100])
    print(f"\n  {_c(BOLD, 'Summary:')}")
    for line in textwrap.wrap(summary.get("summary", ""), width=88, initial_indent="    ", subsequent_indent="    "):
        print(line)
    print(f"\n  {_c(BOLD, 'Why it matters:')}")
    for line in textwrap.wrap(summary.get("why_it_matters_for_main_paper", ""), width=88, initial_indent="    ", subsequent_indent="    "):
        print(line)
    if summary.get("possible_contradiction"):
        print(f"\n  {_c(RED + BOLD, '⚠ Possible contradiction:')} {summary['possible_contradiction'][:200]}")
    evid = summary.get("supporting_evidence", [])
    if evid:
        print(f"\n  {_c(BOLD, 'Supporting evidence:')}")
        bullet(evid[:3], color=DIM)

    # Critique
    header("Critique", "peer-review simulation · missing ablations · statistical gaps")
    findings = cr.get("findings", [])
    critique_findings = [f for f in findings if f.get("agent") == "Critique"]
    if critique_findings:
        for i, f in enumerate(critique_findings):
            finding_block(f, i)
    else:
        print(f"  {_c(DIM, '(no critique findings in citation response — run manually below)')}")

    # Code
    header("Code", "repo discovery · claim↔implementation mapping · gap detection")
    code = cr.get("code", {})
    repo = code.get("repo", {})
    section_line("Repo",        repo.get("full_name", repo.get("name", "N/A")))
    section_line("Stars",       str(repo.get("stargazers_count", "N/A")))
    section_line("Description", str(repo.get("description", ""))[:100])
    if code.get("paper_claim_connection"):
        print(f"\n  {_c(BOLD, 'Claim ↔ implementation:')}")
        for line in textwrap.wrap(code["paper_claim_connection"], width=88, initial_indent="    ", subsequent_indent="    "):
            print(line)
    if code.get("key_files"):
        print(f"\n  {_c(BOLD, 'Key files:')}")
        for kf in code["key_files"][:4]:
            print(f"    {_c(CYAN, kf.get('path', '')[:40]):45s} {_c(DIM, kf.get('why_relevant','')[:60])}")
    if code.get("code_gaps"):
        print(f"\n  {_c(BOLD, 'Code gaps (paper vs repo):')}")
        bullet(code["code_gaps"][:4], color=YELLOW)
    if code.get("implementation_risks"):
        print(f"\n  {_c(BOLD, 'Implementation risks:')}")
        bullet(code["implementation_risks"][:3], color=RED)

    # Replication
    header("Replication", "reproducibility scorecard · step-by-step dry run plan")
    rep = cr.get("replication", {})
    section_line("Claim under test", str(rep.get("claim_under_test", ""))[:100])
    section_line("Expected metric",  str(rep.get("expected_metric", ""))[:100])
    section_line("Environment",      str(rep.get("environment", ""))[:80])
    sc = rep.get("scorecard", {})
    if sc:
        print(f"\n  {_c(BOLD, 'Scorecard:')}")
        for k, v in sc.items():
            tick = _c(GREEN, "✓") if v is True else (_c(RED, "✗") if v is False else _c(DIM, str(v)))
            print(f"    {k:25s} {tick}")
    if rep.get("minimal_reproduction_steps"):
        print(f"\n  {_c(BOLD, 'Reproduction steps:')}")
        for i, step in enumerate(rep["minimal_reproduction_steps"][:5], 1):
            print(f"    {_c(DIM, str(i) + '.')} {step}")
    if rep.get("discrepancies"):
        print(f"\n  {_c(RED + BOLD, 'Discrepancies:')}")
        bullet(rep["discrepancies"][:3], color=RED)
    if rep.get("risks"):
        print(f"\n  {_c(BOLD, 'Risks:')}")
        bullet(rep["risks"][:3], color=YELLOW)

    # Adversarial
    header("Adversarial", "stress tests · OOD robustness · hyperparameter sensitivity")
    adv = cr.get("adversarial", {})
    tests = adv.get("tests", [])
    section_line("Tests generated", str(len(tests)))
    for t in tests[:4]:
        sev_color = SEV_COLOR.get(t.get("severity", "low"), WHITE)
        print(f"\n  {_c(sev_color + BOLD, '[' + t.get('severity','?').upper() + ']')} {_c(BOLD, t.get('name','?'))}")
        desc = t.get("description", "")
        for line in textwrap.wrap(desc, width=88, initial_indent="    ", subsequent_indent="    "):
            print(line)
        if t.get("expected_outcome"):
            print(f"    {_c(DIM, 'Expected: ')}{t['expected_outcome'][:120]}")

    # 4. Manual agent runs for Evaluation (not included in citation click response)
    print(f"\n{_c(DIM, '  Running Evaluation Agent manually …')}", end="", flush=True)
    ev_resp = _post(f"/api/sessions/{sid}/agents/evaluation/run", {"paper_id": paper["id"]})
    ev_findings = ev_resp["output"].get("findings", [])
    print("\r", end="")
    header("Evaluation", "benchmark gap analysis · newer evaluation suites · OOD probes")
    section_line("Benchmark findings", str(len(ev_findings)))
    for f in ev_findings[:4]:
        finding_block(f, 0)

    # 5. Critique agent (manual — shows full deduped result set)
    print(f"\n{_c(DIM, '  Running Critique Agent manually …')}", end="", flush=True)
    cr2 = _post(f"/api/sessions/{sid}/agents/critique/run", {"paper_id": paper["id"]})
    all_crit = cr2["output"].get("findings", [])
    print("\r", end="")
    header("Critique (standalone run)", "full finding set against the main paper")
    section_line("Total findings", str(len(all_crit)))
    for f in all_crit:
        finding_block(f, 0)

    # 6. Final session summary
    final = _get(f"/api/sessions/{sid}")
    print(f"\n{_c(BOLD + CYAN, '═' * 70)}")
    print(f"{_c(BOLD + CYAN, '  SESSION SUMMARY')}")
    print(f"{_c(BOLD + CYAN, '═' * 70)}")
    section_line("Session ID",     sid)
    section_line("Total events",   str(len(final["events"])))
    section_line("Total findings", str(len(final["findings"])))
    section_line("Graph nodes",    str(len(final["graph"]["nodes"])))
    section_line("Graph edges",    str(len(final["graph"]["edges"])))
    agent_counts: dict[str, int] = {}
    for ev in final["events"]:
        a = ev.get("agent") or "System"
        agent_counts[a] = agent_counts.get(a, 0) + 1
    print(f"\n  {_c(BOLD, 'Events per agent:')}")
    for agent_name, count in sorted(agent_counts.items()):
        bar_len = min(count * 2, 40)
        bar = _c(AGENT_COLOR.get(agent_name, WHITE), "█" * bar_len)
        print(f"    {agent_name:15s} {bar} {_c(DIM, str(count))}")
    print()

# ── In-process mode ────────────────────────────────────────────────────────────

async def run_inprocess() -> None:
    sys.path.insert(0, str(Path(__file__).parent / "backend"))
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

    from app.agents.adversarial_agent import run_adversarial_agent
    from app.agents.code_agent import run_code_agent
    from app.agents.critique_agent import run_critique_agent
    from app.agents.evaluation_agent import run_evaluation_agent
    from app.agents.parser_agent import run_parser_agent
    from app.agents.reference_agent import run_reference_agent
    from app.agents.replication_agent import run_replication_agent
    from app.store import store

    print(f"\n{_c(BOLD + CYAN, '═' * 70)}")
    print(f"{_c(BOLD + CYAN, '  DeepPaper — Full 7-Agent Pipeline Demo (in-process mode)')}")
    print(f"{_c(BOLD + CYAN, '═' * 70)}")
    print(f"  {_c(DIM, 'Running agents directly — no HTTP server needed')}\n")

    events_log: list[dict] = []

    def emitter(session_id, type_, message, agent="", status="", payload=None):
        events_log.append({"type": type_, "agent": agent, "status": status, "message": message})
        status_color = GREEN if status == "done" else (RED if status == "failed" else YELLOW)
        print(f"  {_c(DIM, '[event]')} {_c(AGENT_COLOR.get(agent, WHITE), agent or 'System'):15s}"
              f" {_c(status_color, status or ''):10s} {_c(DIM, message[:80])}")

    session = store.create_session()

    # Parser
    header("Parser", "arXiv extraction · section splitting · claim extraction")
    paper = await run_parser_agent(session, "demo", "", emitter)
    section_line("Title",    paper.title)
    section_line("Authors",  ", ".join(paper.authors[:4]))
    section_line("Sections", str(len(paper.sections)))
    section_line("Citations",str(len(paper.citations)))
    section_line("Claims",   str(len(paper.claims)))
    if paper.claims:
        print(f"\n  {_c(BOLD, 'Extracted claims:')}")
        for c in paper.claims:
            conf = f"{c.confidence:.0%}"
            line = textwrap.fill(c.text, width=85, subsequent_indent="       ")
            print(f"    {_c(DIM, conf)}  {line}")

    # Reference
    header("Reference", "citation resolution · relationship · contradiction detection")
    citation = paper.citations[0] if paper.citations else None
    if citation:
        ref_result = await run_reference_agent(session, paper, citation, emitter)
        ref_paper = ref_result["referenced_paper"]
        summary   = ref_result["summary"]
        section_line("Referenced paper", ref_paper.title[:80])
        section_line("Relationship",     summary.get("relationship", "")[:100])
        print(f"\n  {_c(BOLD, 'Summary:')}")
        for line in textwrap.wrap(summary.get("summary", ""), width=88, initial_indent="    ", subsequent_indent="    "):
            print(line)
        if summary.get("possible_contradiction"):
            print(f"\n  {_c(RED + BOLD, '⚠ Possible contradiction:')} {summary['possible_contradiction'][:200]}")

    # Critique
    header("Critique", "peer-review simulation · missing ablations · statistical gaps")
    section = paper.sections[1] if len(paper.sections) > 1 else paper.sections[0] if paper.sections else None
    findings = await run_critique_agent(session, paper, section, paper, emitter)
    section_line("Findings", str(len(findings)))
    for f in findings:
        finding_block(f.model_dump(), 0)

    # Code
    header("Code", "repo discovery · claim↔implementation mapping · gap detection")
    code_result = await run_code_agent(session, paper, finding=findings[0] if findings else None, event_emitter=emitter)
    repo = code_result.get("repo", {})
    section_line("Repo",        repo.get("full_name", repo.get("name", "N/A")))
    section_line("Description", str(repo.get("description", ""))[:100])
    if code_result.get("paper_claim_connection"):
        print(f"\n  {_c(BOLD, 'Claim ↔ implementation:')}")
        for line in textwrap.wrap(code_result["paper_claim_connection"], width=88, initial_indent="    ", subsequent_indent="    "):
            print(line)
    if code_result.get("key_files"):
        print(f"\n  {_c(BOLD, 'Key files:')}")
        for kf in code_result["key_files"][:4]:
            print(f"    {_c(CYAN, kf.get('path', '')[:40]):45s} {_c(DIM, kf.get('why_relevant','')[:60])}")
    if code_result.get("code_gaps"):
        print(f"\n  {_c(BOLD, 'Code gaps:')}")
        bullet(code_result["code_gaps"][:4], color=YELLOW)

    # Replication
    header("Replication", "reproducibility scorecard · dry run plan")
    rep = await run_replication_agent(session, paper, repo=repo, finding=findings[0] if findings else None, event_emitter=emitter)
    section_line("Claim under test", str(rep.get("claim_under_test", ""))[:100])
    section_line("Expected metric",  str(rep.get("expected_metric", ""))[:100])
    sc = rep.get("scorecard", {})
    if sc:
        print(f"\n  {_c(BOLD, 'Scorecard:')}")
        for k, v in sc.items():
            tick = _c(GREEN, "✓") if v is True else (_c(RED, "✗") if v is False else _c(DIM, str(v)))
            print(f"    {k:25s} {tick}")
    if rep.get("minimal_reproduction_steps"):
        print(f"\n  {_c(BOLD, 'Reproduction steps:')}")
        for i, step in enumerate(rep["minimal_reproduction_steps"][:5], 1):
            print(f"    {_c(DIM, str(i) + '.')} {step}")

    # Evaluation
    header("Evaluation", "benchmark gap analysis · newer evaluation suites · OOD probes")
    eval_section = next((s for s in paper.sections if "eval" in s.type or "result" in s.type), section)
    eval_findings = await run_evaluation_agent(session, paper, section=eval_section, event_emitter=emitter)
    section_line("Benchmark findings", str(len(eval_findings)))
    for f in eval_findings[:4]:
        finding_block(f.model_dump(), 0)

    # Adversarial
    header("Adversarial", "stress tests · OOD robustness · hyperparameter sensitivity")
    adv = await run_adversarial_agent(session, paper, repo=repo, event_emitter=emitter)
    tests = adv.get("tests", [])
    section_line("Tests generated", str(len(tests)))
    for t in tests[:4]:
        sev_color = SEV_COLOR.get(t.get("severity", "low"), WHITE)
        print(f"\n  {_c(sev_color + BOLD, '[' + t.get('severity','?').upper() + ']')} {_c(BOLD, t.get('name','?'))}")
        for line in textwrap.wrap(t.get("description",""), width=88, initial_indent="    ", subsequent_indent="    "):
            print(line)

    # Summary
    print(f"\n{_c(BOLD + CYAN, '═' * 70)}")
    print(f"{_c(BOLD + CYAN, '  SESSION SUMMARY')}")
    print(f"{_c(BOLD + CYAN, '═' * 70)}")
    agent_counts: dict[str, int] = {}
    for ev in events_log:
        a = ev.get("agent") or "System"
        agent_counts[a] = agent_counts.get(a, 0) + 1
    section_line("Total events fired", str(len(events_log)))
    print(f"\n  {_c(BOLD, 'Events per agent:')}")
    for agent_name, count in sorted(agent_counts.items()):
        bar = _c(AGENT_COLOR.get(agent_name, WHITE), "█" * min(count * 2, 40))
        print(f"    {agent_name:15s} {bar} {_c(DIM, str(count))}")
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeepPaper agent demo")
    parser.add_argument("--inprocess", action="store_true",
                        help="Run agents directly without the HTTP server")
    args = parser.parse_args()

    if args.inprocess:
        asyncio.run(run_inprocess())
    else:
        run_via_http()
