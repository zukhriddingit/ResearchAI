from __future__ import annotations

from app.models import AgentTrigger, EquationExtract, Paper
from app.services.llm import complete_json, reasoning_model
from app.services.weave_tracing import op as weave_op


MATH_EXPLAIN_PROMPT = """You are a mathematical notation expert for research papers.
Explain each equation in plain English using the paper context.
Return JSON with: name, plain_english, variables, role_in_paper, related_concepts, correctness_notes."""

MATH_AUDIT_PROMPT = """You are a mathematical peer reviewer for research papers.
Identify undefined symbols, dimension mismatches, missing assumptions, and equations that do not support the claimed result.
Return JSON: {"issues": [{"severity": "low|medium|high", "equation_label": "...", "title": "...", "description": "..."}], "overall_assessment": "..."}."""


@weave_op
async def run_math_agent(session, paper: Paper, section=None, event_emitter=None) -> dict:
    if event_emitter:
        event_emitter(session.session_id, "agent.started", "Math Agent started.", agent="Math", status="running")

    equations = _target_equations(paper, section)
    if not equations:
        if event_emitter:
            event_emitter(session.session_id, "agent.finished", "Math Agent found no equations to analyze.", agent="Math", status="done")
        return {"explanations": [], "audit": {"issues": [], "overall_assessment": "No equations found."}, "triggers": []}

    explanations = []
    for equation in equations[:20]:
        explanations.append(await _explain_equation(paper, equation))

    audit = await _audit_math(paper, equations)
    triggers = _build_triggers(audit)

    if event_emitter:
        for issue in audit.get("issues", []):
            if isinstance(issue, dict):
                event_emitter(
                    session.session_id,
                    "math.issue",
                    str(issue.get("title") or "Math issue"),
                    agent="Math",
                    status=str(issue.get("severity") or "medium"),
                    payload=issue,
                )
        event_emitter(
            session.session_id,
            "agent.finished",
            f"Math Agent explained {len(explanations)} equation(s) and found {len(audit.get('issues', []))} issue(s).",
            agent="Math",
            status="done",
            payload={"explanations": len(explanations), "issues": len(audit.get("issues", [])), "triggers": triggers},
        )

    return {"explanations": explanations, "audit": audit, "triggers": triggers}


def _target_equations(paper: Paper, section) -> list[EquationExtract]:
    if section and section.equations:
        return section.equations
    if paper.equations:
        return paper.equations
    equations: list[EquationExtract] = []
    for paper_section in paper.sections:
        equations.extend(paper_section.equations)
    return equations


@weave_op
async def _explain_equation(paper: Paper, equation: EquationExtract) -> dict:
    label = f"Equation {equation.label}" if equation.label else "Unlabelled equation"
    fallback = {
        "name": label,
        "plain_english": f"Mathematical expression: {equation.raw[:200]}",
        "variables": [],
        "role_in_paper": "Part of the paper's mathematical formulation.",
        "related_concepts": [],
        "correctness_notes": "Automatic explanation could not determine more detail.",
    }
    result = await complete_json(
        MATH_EXPLAIN_PROMPT,
        (
            f"Paper: {paper.title}\n"
            f"{label}\n"
            f"LaTeX: {equation.latex}\n"
            f"Raw text: {equation.raw}\n"
            f"Context before: {equation.context_before}\n"
            f"Context after: {equation.context_after}\n"
        ),
        fallback,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=700,
    )
    return {
        "eq_id": equation.id,
        "label": equation.label,
        "raw": equation.raw,
        "latex": equation.latex,
        "section_id": equation.section_id,
        **result,
    }


@weave_op
async def _audit_math(paper: Paper, equations: list[EquationExtract]) -> dict:
    equations_summary = "\n".join(f"{equation.label or 'unlabelled'}: {equation.raw[:180]}" for equation in equations[:20])
    fallback = {"issues": [], "overall_assessment": "No automatic math issues were detected."}
    return await complete_json(
        MATH_AUDIT_PROMPT,
        f"Paper: {paper.title}\nAbstract: {paper.abstract or ''}\nEquations:\n{equations_summary}",
        fallback,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=900,
    )


def _build_triggers(audit: dict) -> list[dict]:
    triggers: list[dict] = []
    for issue in audit.get("issues", []):
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "low")
        if severity in {"medium", "high"}:
            triggers.append(
                AgentTrigger(
                    target="critique",
                    reason="math_issue_found",
                    context={
                        "equation_label": issue.get("equation_label", ""),
                        "title": issue.get("title", "Math issue"),
                        "description": str(issue.get("description", ""))[:300],
                        "severity": severity,
                    },
                ).model_dump()
            )
        if severity == "high":
            triggers.append(
                AgentTrigger(
                    target="code",
                    reason="equation_error",
                    context={
                        "equation_label": issue.get("equation_label", ""),
                        "description": str(issue.get("description", ""))[:300],
                    },
                ).model_dump()
            )
    return triggers
