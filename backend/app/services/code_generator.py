from __future__ import annotations

import ast
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from app.models import EquationExtract, Paper
from app.services.llm import complete_json, complete_text, reasoning_model
from app.services.weave_tracing import op as weave_op


PROJECT_PLAN_PROMPT = """You are a senior ML research engineer.
Design a complete, runnable Python project for implementing a research paper.

Return JSON with:
{
  "project_name": "kebab-case-name",
  "description": "one sentence",
  "files": [
    {
      "path": "src/package/model.py",
      "description": "what this file does",
      "content_hint": "classes/functions to include",
      "depends_on": [],
      "priority": 1
    }
  ]
}

Rules:
- Generate 10-16 files.
- Include src package code, configs/default.yaml, data/dataset.py, train.py, evaluate.py,
  tests/test_model.py, scripts/reproduce.sh, requirements.txt, setup.py, README.md, .gitignore.
- Use PyTorch unless the paper clearly requires another stack.
- Priorities: 1 core model, 2 data/train, 3 eval/config/utils, 4 tests/scripts/docs."""

FILE_PROMPT = """You are a senior ML research engineer writing one file in a generated research-code project.

Output raw file content only. No markdown fences.

Quality rules:
- Type hints for Python functions.
- Docstrings for public classes/functions.
- Use TODO comments only for paper details that are truly underspecified.
- Keep code runnable with the files described in the plan.
- For tests, use pytest and check tensor shapes or one core equation.
- For configs/default.yaml, include model, training, data, and eval sections.
- For shell scripts, include a shebang and set -e."""

README_PROMPT = """You are writing README.md for a generated research implementation.
Output raw Markdown only. Include overview, installation, quick start, reproduction, project structure, and citation placeholder."""


@dataclass
class ProjectResult:
    project_name: str
    description: str
    files: dict[str, str]
    file_plan: list[dict[str, Any]]
    zip_bytes: bytes

    def to_json_safe(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "description": self.description,
            "file_count": len(self.files),
            "file_list": [
                {"path": item.get("path", ""), "description": item.get("description", "")}
                for item in self.file_plan
            ],
            "total_lines": sum(content.count("\n") + 1 for content in self.files.values()),
        }


@weave_op
async def generate_full_project(
    paper: Paper,
    repo: dict[str, Any],
    equations: list[EquationExtract] | None = None,
    event_emitter=None,
    session=None,
) -> ProjectResult:
    def emit_progress(message: str, status: str = "running", payload: dict[str, Any] | None = None) -> None:
        if event_emitter and session:
            event_emitter(session.session_id, "codegen.progress", message, agent="Code", status=status, payload=payload or {})

    emit_progress("Planning a multi-file project.")
    plan = await _plan_project(paper, repo)
    project_name = _safe_project_name(str(plan.get("project_name") or paper.title))
    file_plan = _normalize_file_plan(plan, project_name, paper)
    emit_progress(f"Project plan ready: {len(file_plan)} files.", payload={"project_name": project_name, "file_count": len(file_plan)})

    generated: dict[str, str] = {}
    for priority in sorted({int(item.get("priority", 3)) for item in file_plan}):
        batch = [item for item in file_plan if int(item.get("priority", 3)) == priority]
        emit_progress(f"Generating priority {priority} files.", payload={"files": [item["path"] for item in batch]})
        for item in batch:
            path = str(item["path"])
            if path == "README.md":
                continue
            content = await _generate_file(paper, repo, plan, item, generated, equations or paper.equations)
            generated[path] = _validated_content(path, content, project_name, paper)

    emit_progress("Generating README.md.")
    generated["README.md"] = await _generate_readme(paper, plan, generated)

    emit_progress("Validating generated Python syntax.")
    generated = {
        path: _validated_content(path, content, project_name, paper)
        for path, content in generated.items()
    }
    zip_bytes = _create_zip(project_name, generated)
    emit_progress(f"ZIP ready with {len(generated)} files.", status="done", payload={"project_name": project_name})

    return ProjectResult(
        project_name=project_name,
        description=str(plan.get("description") or f"Implementation of {paper.title}"),
        files=generated,
        file_plan=file_plan,
        zip_bytes=zip_bytes,
    )


async def _plan_project(paper: Paper, repo: dict[str, Any]) -> dict[str, Any]:
    method_text = _method_text(paper, limit=2600)
    fallback = {
        "project_name": _safe_project_name(paper.title),
        "description": f"Python implementation scaffold for {paper.title}.",
        "files": _default_file_plan(_safe_project_name(paper.title), paper),
    }
    return await complete_json(
        PROJECT_PLAN_PROMPT,
        (
            f"Paper: {paper.title}\n"
            f"Authors: {', '.join(paper.authors[:5])}\n"
            f"Year: {paper.year or 'unknown'}\n"
            f"Repository context: {repo.get('full_name') or repo.get('name') or 'none'} - {repo.get('description') or ''}\n"
            f"Claims:\n{_claims_text(paper)}\n\n"
            f"Method excerpt:\n{method_text}"
        ),
        fallback,
        model=reasoning_model(),
        temperature=0.15,
        max_tokens=1600,
    )


async def _generate_file(
    paper: Paper,
    repo: dict[str, Any],
    plan: dict[str, Any],
    file_plan: dict[str, Any],
    generated: dict[str, str],
    equations: list[EquationExtract],
) -> str:
    path = str(file_plan.get("path") or "src/model.py")
    dependencies = [dep for dep in file_plan.get("depends_on", []) if dep in generated]
    dependency_context = "\n\n".join(
        f"### {dep}\n{generated[dep][:1800]}"
        for dep in dependencies[:3]
    ) or "No dependency files generated yet."
    equation_text = "\n".join(
        f"- {equation.label or equation.id}: {(equation.latex or equation.raw)[:180]}"
        for equation in equations[:8]
        if equation.latex or equation.raw
    ) or "No equations extracted."
    fallback = _fallback_file(path, str(plan.get("project_name") or "paper-impl"), paper)
    return await complete_text(
        FILE_PROMPT,
        (
            f"Project: {plan.get('project_name')}\n"
            f"Paper: {paper.title}\n"
            f"File path: {path}\n"
            f"Purpose: {file_plan.get('description')}\n"
            f"Content hint: {file_plan.get('content_hint')}\n"
            f"Repository context: {repo.get('full_name') or repo.get('name') or 'none'}\n"
            f"Claims:\n{_claims_text(paper)}\n\n"
            f"Equations:\n{equation_text}\n\n"
            f"Method excerpt:\n{_method_text(paper, limit=2800)}\n\n"
            f"Dependency context:\n{dependency_context}"
        ),
        fallback,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=2600,
    )


async def _generate_readme(paper: Paper, plan: dict[str, Any], generated: dict[str, str]) -> str:
    file_tree = "\n".join(f"- {path}" for path in sorted(generated))
    fallback = f"# {paper.title}\n\nGenerated implementation scaffold.\n\n## Installation\n\n```bash\npip install -e .\n```\n"
    return await complete_text(
        README_PROMPT,
        (
            f"Paper: {paper.title}\n"
            f"Authors: {', '.join(paper.authors[:6])}\n"
            f"Abstract: {paper.abstract or ''}\n"
            f"Project: {plan.get('project_name')}\n"
            f"Description: {plan.get('description')}\n"
            f"Files:\n{file_tree}"
        ),
        fallback,
        model=reasoning_model(),
        temperature=0.1,
        max_tokens=1800,
    )


def _normalize_file_plan(plan: dict[str, Any], project_name: str, paper: Paper) -> list[dict[str, Any]]:
    raw_files = plan.get("files") if isinstance(plan.get("files"), list) else []
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        path = _safe_relative_path(str(item.get("path") or ""))
        if not path or path in seen:
            continue
        seen.add(path)
        files.append(
            {
                "path": path,
                "description": str(item.get("description") or "Generated project file."),
                "content_hint": str(item.get("content_hint") or ""),
                "depends_on": [str(dep) for dep in item.get("depends_on", []) if isinstance(dep, str)],
                "priority": int(item.get("priority") or 3),
            }
        )
    for item in _default_file_plan(project_name, paper):
        if item["path"] not in seen:
            files.append(item)
            seen.add(item["path"])
    return sorted(files[:18], key=lambda item: (int(item.get("priority", 3)), str(item.get("path"))))


def _default_file_plan(project_name: str, paper: Paper) -> list[dict[str, Any]]:
    package = project_name.replace("-", "_")
    return [
        {"path": f"src/{package}/__init__.py", "description": "Package exports.", "content_hint": "__all__ exports.", "depends_on": [], "priority": 1},
        {"path": f"src/{package}/layers.py", "description": "Core layers from the method.", "content_hint": "Reusable torch modules.", "depends_on": [], "priority": 1},
        {"path": f"src/{package}/model.py", "description": "Main model implementation.", "content_hint": "Model class and forward pass.", "depends_on": [f"src/{package}/layers.py"], "priority": 1},
        {"path": "data/dataset.py", "description": "Dataset and preprocessing hooks.", "content_hint": "PyTorch Dataset with paper assumptions.", "depends_on": [], "priority": 2},
        {"path": "train.py", "description": "Training entrypoint.", "content_hint": "Argument parser, config loading, training loop.", "depends_on": [f"src/{package}/model.py", "data/dataset.py"], "priority": 2},
        {"path": "configs/default.yaml", "description": "Paper hyperparameters and assumptions.", "content_hint": "model/training/data/eval sections.", "depends_on": [], "priority": 3},
        {"path": "evaluate.py", "description": "Evaluation entrypoint.", "content_hint": "Metrics aligned with paper claims.", "depends_on": [f"src/{package}/model.py"], "priority": 3},
        {"path": "utils.py", "description": "Shared utilities.", "content_hint": "Seed, metrics, checkpoints.", "depends_on": [], "priority": 3},
        {"path": "requirements.txt", "description": "Python dependencies.", "content_hint": "Pinned practical dependencies.", "depends_on": [], "priority": 3},
        {"path": "setup.py", "description": "Installable package setup.", "content_hint": "setuptools config.", "depends_on": [], "priority": 3},
        {"path": ".gitignore", "description": "Python gitignore.", "content_hint": "cache/checkpoint/run artifacts.", "depends_on": [], "priority": 3},
        {"path": "tests/test_model.py", "description": "Shape and smoke tests.", "content_hint": "pytest tests for model forward.", "depends_on": [f"src/{package}/model.py"], "priority": 4},
        {"path": "scripts/reproduce.sh", "description": "Reproduction script.", "content_hint": "Minimal commands to run train/eval.", "depends_on": [], "priority": 4},
        {"path": "README.md", "description": "Project documentation.", "content_hint": "Generated last.", "depends_on": [], "priority": 5},
    ]


def _validated_content(path: str, content: str, project_name: str, paper: Paper) -> str:
    cleaned = _strip_fences(content)
    if not cleaned.strip():
        return _fallback_file(path, project_name, paper)
    if path.endswith(".py"):
        try:
            ast.parse(cleaned)
        except SyntaxError:
            return _fallback_file(path, project_name, paper)
    return cleaned


def _create_zip(project_name: str, files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            archive.writestr(f"{project_name}/{path}", content.encode("utf-8", errors="replace"))
    return buffer.getvalue()


def _method_text(paper: Paper, limit: int) -> str:
    preferred = next(
        (section.text for section in paper.sections if section.type in {"method", "methods", "methodology", "approach"}),
        "",
    )
    text = preferred or paper.abstract or " ".join(section.text for section in paper.sections[:2])
    return text[:limit]


def _claims_text(paper: Paper) -> str:
    return "\n".join(f"- {claim.text}" for claim in paper.claims[:6]) or "- No structured claims extracted."


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
    cleaned = re.sub(r"\n```$", "", cleaned)
    return cleaned.strip()


def _safe_project_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:44] or "paper-implementation"


def _safe_relative_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip().lstrip("/")
    parts = [part for part in cleaned.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)


def _fallback_file(path: str, project_name: str, paper: Paper) -> str:
    package = _safe_project_name(project_name).replace("-", "_")
    if path == "requirements.txt":
        return "torch>=2.1.0\nnumpy>=1.24.0\npyyaml>=6.0\npytest>=8.0.0\ntqdm>=4.66.0\n"
    if path == ".gitignore":
        return "__pycache__/\n*.py[cod]\n.venv/\n.env\nruns/\ncheckpoints/\n*.pt\n*.pth\n"
    if path == "configs/default.yaml":
        return "model:\n  hidden_dim: 256\n  dropout: 0.1\ntraining:\n  batch_size: 32\n  learning_rate: 1.0e-4\n  epochs: 10\ndata:\n  path: data/raw\neval:\n  batch_size: 32\n"
    if path == "setup.py":
        return f'from setuptools import find_packages, setup\n\nsetup(name="{project_name}", version="0.1.0", packages=find_packages("src"), package_dir={{"": "src"}})\n'
    if path.endswith(".sh"):
        return "#!/usr/bin/env bash\nset -e\n\npython train.py --config configs/default.yaml\npython evaluate.py --config configs/default.yaml\n"
    if path == "README.md":
        return f"# {paper.title}\n\nGenerated project for reproducing the paper's core method.\n"
    if path.endswith("__init__.py"):
        return '"""Generated research implementation package."""\n'
    if path == "tests/test_model.py":
        return (
            "from __future__ import annotations\n\n"
            "import torch\n\n\n"
            "def test_tensor_smoke() -> None:\n"
            "    tensor = torch.randn(2, 4)\n"
            "    assert tensor.shape == (2, 4)\n"
        )
    return (
        f'"""{path} for {paper.title}."""\n'
        "from __future__ import annotations\n\n"
        "import torch\n"
        "from torch import nn\n\n\n"
        "class GeneratedModel(nn.Module):\n"
        f'    """Minimal validated scaffold for {paper.title}."""\n\n'
        "    def __init__(self, input_dim: int = 128, hidden_dim: int = 256) -> None:\n"
        "        super().__init__()\n"
        "        self.net = nn.Sequential(nn.Linear(input_dim, hidden_dim), nn.GELU(), nn.Linear(hidden_dim, input_dim))\n\n"
        "    def forward(self, inputs: torch.Tensor) -> torch.Tensor:\n"
        '        """Run a forward pass."""\n'
        "        return self.net(inputs)\n"
        f"\n\n# Package hint: import from src/{package}/ as the implementation is completed.\n"
    )
