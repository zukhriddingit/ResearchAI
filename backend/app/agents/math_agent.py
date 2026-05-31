from __future__ import annotations

from app.models import AgentFinding, AgentTrigger, EquationExtract, Paper, new_id
from app.services.llm import complete_json
from app.services.weave_tracing import op as weave_op


MATH_EXPLAIN_PROMPT = """\
You are a mathematical notation expert for research papers.

Given an equation from a research paper, explain it in plain English with full context.

Return JSON:
{
  "name": "Short name for this equation (e.g. 'Low-Rank Update Rule', 'Loss Function')",
  "plain_english": "What this equation computes or represents in 1-2 sentences.",
  "variables": [
    {"symbol": "W", "meaning": "weight matrix being updated"}
  ],
  "role_in_paper": "How this equation relates to the paper's core contribution.",
  "related_concepts": ["linear algebra", "gradient descent"],
  "correctness_notes": "Any assumptions, edge cases, or potential issues with this formulation."
}

Be precise. If you cannot determine the meaning from context, say so explicitly."""

MATH_AUDIT_PROMPT = """\
You are a mathematical peer reviewer for research papers.

Given a list of equations from a paper, identify:
1. Mathematical inconsistencies or undefined symbols
2. Equations that may have errors (wrong sign, missing term, wrong dimension)
3. Claims that depend on an equation that appears unverified
4. Missing equations that the paper references but doesn't show

Return JSON:
{
  "issues": [
    {
      "severity": "low" | "medium" | "high",
      "equation_label": "...",
      "title": "...",
      "description": "..."
    }
  ],
  "overall_assessment": "..."
}"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@weave_op
async def run_math_agent(
    session,
    paper: Paper,
    section=None,
    event_emitter=None,
) -> dict:
    """
    Explain every equation in the paper and audit the math for correctness.

    Returns:
        {
          "explanations": [ { eq_id, label, raw, latex, name, plain_english,
                               variables, role_in_paper, related_concepts,
                               correctness_notes, section_id } ],
          "audit": { issues: [...], overall_assessment: "..." },
          "triggers": [AgentTrigger dicts]
        }

    Triggers emitted:
        → critique: each high/medium math issue becomes a critique finding
        → code:     equations with confirmed correctness issues
    """
    if event_emitter:
        event_emitter(session.session_id, "agent.started",
                      "Math Agent started — explaining equations and auditing math.",
                      agent="Math", status="running")

    # Collect equations: prefer section-scoped if a section is given
    if section and section.equations:
        target_equations = section.equations
    elif paper.equations:
        target_equations = paper.equations
    else:
        # Gather from all sections
        target_equations = []
        for sec in paper.sections:
            target_equations.extend(sec.equations)

    if not target_equations:
        if event_emitter:
            event_emitter(session.session_id, "agent.finished",
                          "Math Agent: no equations found in this paper.",
                          agent="Math", status="done")
        return {"explanations": [], "audit": {"issues": [], "overall_assessment": "No equations found."}, "triggers": []}

    if event_emitter:
        event_emitter(session.session_id, "math.equations_found",
                      f"Math Agent found {len(target_equations)} equations to explain.",
                      agent="Math", status="running",
                      payload={"count": len(target_equations)})

    # ── Explain equations (batch in groups of 5 to avoid huge prompts) ───
    explanations = await _explain_equations_batched(paper, target_equations)

    if event_emitter:
        event_emitter(session.session_id, "math.explained",
                      f"Math Agent explained {len(explanations)} equations.",
                      agent="Math", status="running",
                      payload={"count": len(explanations)})

    # ── Audit all equations for mathematical correctness ─────────────────
    audit = await _audit_math(paper, target_equations)

    # ── Build triggers ────────────────────────────────────────────────────
    triggers: list[dict] = []
    for issue in audit.get("issues", []):
        sev = issue.get("severity", "low")
        if sev in ("high", "medium"):
            triggers.append(AgentTrigger(
                target="critique",
                reason="math_issue_found",
                context={
                    "equation_label": issue.get("equation_label", ""),
                    "title": issue.get("title", ""),
                    "description": issue.get("description", "")[:300],
                    "severity": sev,
                },
            ).model_dump())
        if sev == "high":
            triggers.append(AgentTrigger(
                target="code",
                reason="equation_error",
                context={"equation_label": issue.get("equation_label", ""),
                         "description": issue.get("description", "")[:300]},
            ).model_dump())

    if event_emitter:
        issues = audit.get("issues", [])
        for issue in issues:
            event_emitter(session.session_id, "math.issue",
                          issue.get("title", "Math issue"),
                          agent="Math", status=issue.get("severity", "low"),
                          payload=issue)
        event_emitter(session.session_id, "agent.finished",
                      f"Math Agent finished — {len(explanations)} explanations, "
                      f"{len(issues)} issues.",
                      agent="Math", status="done",
                      payload={"explanations": len(explanations),
                               "issues": len(issues),
                               "triggers": triggers})

    return {"explanations": explanations, "audit": audit, "triggers": triggers}


# ---------------------------------------------------------------------------
# Batch equation explanation
# ---------------------------------------------------------------------------

@weave_op
async def _explain_equations_batched(paper: Paper, equations: list[EquationExtract]) -> list[dict]:
    """Explain equations in batches of 5, each batch is one LLM call."""
    import asyncio

    BATCH = 5
    all_results: list[dict] = []

    for i in range(0, len(equations[:40]), BATCH):  # cap at 40 equations
        batch = equations[i : i + BATCH]
        tasks = [_explain_single(paper, eq) for eq in batch]
        results = await asyncio.gather(*tasks)
        all_results.extend(results)

    return all_results


@weave_op
async def _explain_single(paper: Paper, eq: EquationExtract) -> dict:
    label_str = f"Equation {eq.label}" if eq.label else "Unlabelled equation"
    latex_str = f"LaTeX: `{eq.latex}`\n" if eq.latex else ""
    user_msg = (
        f"Paper: {paper.title}\n"
        f"{label_str}\n"
        f"{latex_str}"
        f"Raw text: {eq.raw}\n"
        f"Context before: {eq.context_before}\n"
        f"Context after:  {eq.context_after}\n"
    )
    fallback = {
        "name": label_str,
        "plain_english": f"Mathematical expression: {eq.raw[:200]}",
        "variables": [],
        "role_in_paper": "Part of the paper's mathematical formulation.",
        "related_concepts": [],
        "correctness_notes": "Could not determine automatically.",
    }
    result = await complete_json(MATH_EXPLAIN_PROMPT, user_msg, fallback)
    return {
        "eq_id": eq.id,
        "label": eq.label,
        "raw": eq.raw,
        "latex": eq.latex,
        "section_id": eq.section_id,
        **result,
    }


# ---------------------------------------------------------------------------
# Math audit
# ---------------------------------------------------------------------------

@weave_op
async def _audit_math(paper: Paper, equations: list[EquationExtract]) -> dict:
    equations_summary = "\n".join(
        f"  {eq.label or 'unlabelled'}: {eq.raw[:200]}"
        for eq in equations[:20]
    )
    user_msg = (
        f"Paper: {paper.title}\n\n"
        f"Equations:\n{equations_summary}\n\n"
        f"Paper abstract: {paper.abstract or ''}[:500]"
    )
    fallback = {
        "issues": [],
        "overall_assessment": "Math audit could not be completed automatically.",
    }
    return await complete_json(MATH_AUDIT_PROMPT, user_msg, fallback)
