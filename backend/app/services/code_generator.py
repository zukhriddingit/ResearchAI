"""
Multi-file research-paper code generator.

Workflow:
  1. plan_project_structure()  — LLM designs file tree + purpose of each file
  2. generate_all_files()      — LLM writes every file, priority-group by priority,
                                  earlier groups feed as context into later groups
  3. create_project_zip()      — packs everything into an in-memory ZIP

Public entry:
  generate_full_project(paper, repo, equations) -> ProjectResult
"""
from __future__ import annotations

import asyncio
import io
import re
import zipfile
from typing import Any

from app.models import EquationExtract, Paper
from app.services.llm import complete_json, complete_text
from app.services.weave_tracing import op as weave_op


def _strip_fences(text: str) -> str:
    """
    Remove markdown code fences.  If the LLM emits multiple fenced blocks
    (e.g. it decided to also show config files after the main file), we keep
    only the first block and discard the rest.
    """
    t = text.strip()
    # Strip opening fence
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    # Take only up to the first closing fence — drops any bonus blocks
    m = re.search(r"\n```", t)
    if m:
        t = t[: m.start()]
    return t.strip()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PROJECT_PLAN_PROMPT = """\
You are a senior ML research engineer. Given a research paper, design a complete Python project structure to implement and reproduce the paper's core contribution.

Return JSON:
{
  "project_name": "kebab-case name (e.g. 'lora-adapter', 'transformer-attn')",
  "description": "One sentence describing what this project implements",
  "tech_stack": ["torch", "numpy"],
  "files": [
    {
      "path": "src/model.py",
      "description": "What this file implements in one sentence",
      "content_hint": "Key classes/functions to include, with brief signatures",
      "depends_on": [],
      "priority": 1
    }
  ]
}

File structure rules:
- src/{project_name}/         core implementation (model, layers, attention, loss, etc.)
- configs/default.yaml        ALL hyperparameters mentioned in the paper
- data/dataset.py             data loading + preprocessing
- train.py                    training loop referencing paper's training procedure
- evaluate.py                 evaluation against paper's benchmarks
- utils.py                    shared helpers (logging, checkpointing, metrics)
- scripts/reproduce.sh        shell commands to reproduce the paper's main result
- tests/test_model.py         unit tests that verify key equations/shapes
- requirements.txt            pinned dependencies
- setup.py                    installable package
- .gitignore                  standard Python gitignore
- README.md                   generated last with full context

Priority:
  1 = core model / layers
  2 = training loop, data loading
  3 = evaluation, utilities, configs
  4 = tests, scripts, docs

Generate 10–18 files. Use PyTorch unless the paper specifies another framework."""


FILE_GEN_SYSTEM = """\
You are a senior ML research engineer implementing a research paper in Python.

Your job: output the COMPLETE, RUNNABLE file content — nothing else.

Rules:
- Output raw file content only (no markdown fences, no explanation, no preamble)
- Type hints on every function signature
- Docstring on every class and public function
- Annotate paper hyperparameters:    # Paper: value = X
- Annotate assumptions not in paper: # Assumption: ...
- configs/default.yaml → YAML with sections: model, training, data, eval
- requirements.txt → one package>=version per line
- README.md → Overview, Installation, Quick Start, Reproducing Results, Citation
- Shell scripts → #!/usr/bin/env bash + set -e + one comment per step
- Tests → pytest, assert correct tensor shapes, test one key equation from the paper
- Never use `pass` — implement fully, or add # TODO: not specified in paper"""

FILE_GEN_USER = """\
Project: {project_name}
Paper: {paper_title} ({paper_year})

File to generate: {file_path}
Purpose: {file_description}
Content hints: {content_hint}

Paper claims:
{claims}

Key equations:
{equations}

Method description:
{method_text}

Other project files (path → purpose):
{other_files_summary}

Dependency files already generated:
{context_files}

Generate {file_path} now."""


README_SYSTEM = """\
You are a technical writer generating a README.md for an open-source Python project.
Output raw Markdown only — no fences, no explanation, no preamble."""

README_USER = """\
Paper: {paper_title} ({paper_year})
Authors: {authors}
Project: {project_name}
Description: {description}

Key claims:
{claims}

Files in the project:
{file_list}

Write the full README.md. Include:
1. Title + badges + one-line description
2. Paper abstract (1 paragraph)
3. Installation (`pip install -e .`)
4. Quick start (Python snippet using the core class)
5. Reproducing paper results (`bash scripts/reproduce.sh`)
6. Project structure (ASCII tree with one-line descriptions)
7. Citation (BibTeX block)"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ProjectResult:
    def __init__(
        self,
        project_name: str,
        description: str,
        files: dict[str, str],
        file_plan: list[dict],
        zip_bytes: bytes,
    ) -> None:
        self.project_name = project_name
        self.description = description
        self.files = files              # path -> content
        self.file_plan = file_plan      # [{path, description, priority}]
        self.zip_bytes = zip_bytes

    def to_json_safe(self) -> dict:
        """Return a serialisable summary (no raw zip bytes, no full file content)."""
        return {
            "project_name": self.project_name,
            "description": self.description,
            "file_count": len(self.files),
            "file_list": [
                {"path": f["path"], "description": f["description"]}
                for f in self.file_plan
            ],
            "total_lines": sum(c.count("\n") for c in self.files.values()),
        }


@weave_op
async def generate_full_project(
    paper: Paper,
    repo: dict,
    equations: list[EquationExtract] | None = None,
    event_emitter=None,
    session=None,
) -> ProjectResult:
    """
    Orchestrate the full project generation pipeline:
      plan → generate files (priority groups) → ZIP
    """
    def _emit(msg: str, status: str = "running") -> None:
        if event_emitter and session:
            event_emitter(session.session_id, "codegen.progress", msg,
                          agent="Code", status=status)

    _emit("Planning project structure …")
    plan = await plan_project_structure(paper, repo)
    project_name = plan["project_name"]
    file_plans: list[dict] = plan.get("files", [])

    _emit(f"Project '{project_name}' — {len(file_plans)} files planned.")

    # Generate files in priority groups so earlier files feed as context
    generated: dict[str, str] = {}
    groups: dict[int, list[dict]] = {}
    for fp in file_plans:
        p = int(fp.get("priority", 3))
        groups.setdefault(p, []).append(fp)

    for priority in sorted(groups):
        batch = groups[priority]
        _emit(f"Generating priority-{priority} files: {[f['path'] for f in batch]}")
        tasks = [
            _generate_one_file(paper, repo, plan, fp, generated, equations)
            for fp in batch
        ]
        results = await asyncio.gather(*tasks)
        for fp, content in zip(batch, results):
            generated[fp["path"]] = content

    # README always last — has full context
    # Note: _generate_one_file returns "" for README as a placeholder; re-generate here.
    if not generated.get("README.md"):
        _emit("Generating README.md …")
        generated["README.md"] = await _generate_readme(paper, plan, generated)

    _emit(f"Packing {len(generated)} files into ZIP …")
    zip_bytes = _create_zip(project_name, generated)

    _emit(f"Done — {len(generated)} files, {sum(c.count(chr(10)) for c in generated.values())} lines total.", "done")

    return ProjectResult(
        project_name=project_name,
        description=plan.get("description", f"Implementation of {paper.title}"),
        files=generated,
        file_plan=file_plans,
        zip_bytes=zip_bytes,
    )


# ---------------------------------------------------------------------------
# Step 1 — project planning
# ---------------------------------------------------------------------------

@weave_op
async def plan_project_structure(paper: Paper, repo: dict) -> dict:
    method_sec = next(
        (s for s in paper.sections
         if s.type in ("methodology", "method", "methods", "approach")),
        paper.sections[1] if len(paper.sections) > 1 else paper.sections[0] if paper.sections else None,
    )
    claims_text = "\n".join(f"- {c.text}" for c in paper.claims[:5])
    repo_ctx = (
        f"Reference repo: {repo.get('full_name','unknown')} — {repo.get('description','')}"
        if repo.get("full_name") else "No public repo found."
    )
    user_msg = (
        f"Paper: {paper.title} ({paper.year or 'unknown year'})\n"
        f"Authors: {', '.join(paper.authors[:4])}\n"
        f"{repo_ctx}\n\n"
        f"Claims:\n{claims_text}\n\n"
        f"Method excerpt:\n{method_sec.text[:2000] if method_sec else 'Not available'}"
    )
    safe = re.sub(r"[^a-z0-9]+", "-", paper.title.lower())[:40].strip("-")
    fallback: dict[str, Any] = {
        "project_name": safe or "paper-impl",
        "description": f"Python implementation of {paper.title}",
        "tech_stack": ["torch", "numpy"],
        "files": _default_file_plan(safe or "paper-impl", paper),
    }
    result = await complete_json(PROJECT_PLAN_PROMPT, user_msg, fallback)
    # Ensure mandatory files are present
    result = _ensure_mandatory_files(result, safe or "paper-impl")
    return result


def _default_file_plan(project_name: str, paper: Paper) -> list[dict]:
    pkg = project_name.replace("-", "_")
    return [
        {"path": f"src/{pkg}/model.py",    "description": "Core model architecture",         "content_hint": "Main model class, forward pass", "depends_on": [], "priority": 1},
        {"path": f"src/{pkg}/layers.py",   "description": "Building-block layers/modules",   "content_hint": "Sub-layers used by model.py",    "depends_on": [], "priority": 1},
        {"path": f"src/{pkg}/__init__.py", "description": "Package init, public exports",    "content_hint": "__all__",                         "depends_on": [f"src/{pkg}/model.py"], "priority": 1},
        {"path": "data/dataset.py",        "description": "Dataset class + data loaders",    "content_hint": "PyTorch Dataset subclass",        "depends_on": [], "priority": 2},
        {"path": "train.py",               "description": "Training loop",                   "content_hint": "Trainer class, main() entry",    "depends_on": [f"src/{pkg}/model.py", "data/dataset.py"], "priority": 2},
        {"path": "evaluate.py",            "description": "Evaluation against paper metrics","content_hint": "evaluate() function",             "depends_on": [f"src/{pkg}/model.py"], "priority": 3},
        {"path": "utils.py",               "description": "Logging, checkpointing, metrics", "content_hint": "Helper functions",               "depends_on": [], "priority": 3},
        {"path": "configs/default.yaml",   "description": "All hyperparameters from paper",  "content_hint": "model, training, data, eval",    "depends_on": [], "priority": 3},
        {"path": "requirements.txt",       "description": "Pinned dependencies",             "content_hint": "torch, numpy + paper deps",      "depends_on": [], "priority": 3},
        {"path": "setup.py",               "description": "Installable package",             "content_hint": "setuptools config",              "depends_on": [], "priority": 3},
        {"path": ".gitignore",             "description": "Standard Python gitignore",       "content_hint": "__pycache__, *.pyc, .env, runs/","depends_on": [], "priority": 3},
        {"path": "tests/test_model.py",    "description": "Unit tests for shapes + equations","content_hint":"pytest, test forward pass",      "depends_on": [f"src/{pkg}/model.py"], "priority": 4},
        {"path": "scripts/reproduce.sh",   "description": "Shell script to reproduce paper", "content_hint": "bash commands, set -e",          "depends_on": [], "priority": 4},
        {"path": "README.md",              "description": "Docs: overview, install, usage",  "content_hint": "Generated last",                 "depends_on": [], "priority": 5},
    ]


def _ensure_mandatory_files(plan: dict, project_name: str) -> dict:
    """Add any missing must-have files that the LLM might have dropped."""
    paths = {f["path"] for f in plan.get("files", [])}
    mandatory = [
        ("requirements.txt",     "Pinned Python dependencies", "", 3),
        ("README.md",            "Project documentation",      "", 5),
        ("configs/default.yaml", "Paper hyperparameters",      "", 3),
    ]
    for path, desc, hint, pri in mandatory:
        if path not in paths:
            plan.setdefault("files", []).append(
                {"path": path, "description": desc, "content_hint": hint,
                 "depends_on": [], "priority": pri}
            )
    return plan


# ---------------------------------------------------------------------------
# Step 2 — per-file generation
# ---------------------------------------------------------------------------

@weave_op
async def _generate_one_file(
    paper: Paper,
    repo: dict,
    plan: dict,
    file_plan: dict,
    already_generated: dict[str, str],
    equations: list[EquationExtract] | None,
) -> str:
    if file_plan["path"] == "README.md":
        return ""   # generated separately at the end

    # Equations summary (first 12 real ones with LaTeX)
    eq_lines: list[str] = []
    for eq in (equations or paper.equations)[:12]:
        src = eq.latex or eq.raw
        if src and len(src) > 8:
            label = f"({eq.label}) " if eq.label else ""
            eq_lines.append(f"  {label}{src[:160]}")
    eq_text = "\n".join(eq_lines) or "  No equations extracted."

    # Method text
    method_sec = next(
        (s for s in paper.sections
         if s.type in ("methodology", "method", "methods", "approach")),
        None,
    )
    method_text = method_sec.text[:2500] if method_sec else (
        paper.sections[0].text[:1500] if paper.sections else ""
    )

    # Other files summary — just path + description, keeps context small
    other_summary = "\n".join(
        f"  {f['path']}: {f['description']}"
        for f in plan.get("files", [])
        if f["path"] != file_plan["path"]
    )

    # Context files — full content of direct dependencies (capped to avoid prompt blowout)
    deps = file_plan.get("depends_on", [])
    context_parts: list[str] = []
    total_ctx_chars = 0
    for dep in deps:
        if dep in already_generated and total_ctx_chars < 4000:
            snippet = already_generated[dep][:2000]
            context_parts.append(f"### {dep}\n```python\n{snippet}\n```")
            total_ctx_chars += len(snippet)
    context_files = "\n\n".join(context_parts) or "  (none yet)"

    claims_text = "\n".join(f"  - {c.text}" for c in paper.claims[:5])

    user_msg = FILE_GEN_USER.format(
        project_name=plan.get("project_name", "paper-impl"),
        paper_title=paper.title,
        paper_year=paper.year or "unknown",
        file_path=file_plan["path"],
        file_description=file_plan.get("description", ""),
        content_hint=file_plan.get("content_hint", ""),
        claims=claims_text or "  (no claims extracted)",
        equations=eq_text,
        method_text=method_text,
        other_files_summary=other_summary,
        context_files=context_files,
    )

    fallback_content = _fallback_file(file_plan["path"], plan.get("project_name", "impl"), paper)
    raw = await complete_text(FILE_GEN_SYSTEM, user_msg, fallback_content)
    content = _strip_fences(raw)

    if len(content.strip()) < 30:
        content = fallback_content

    return content


@weave_op
async def _generate_readme(paper: Paper, plan: dict, generated: dict[str, str]) -> str:
    claims_text = "\n".join(f"- {c.text}" for c in paper.claims[:5])
    file_list = "\n".join(
        f"  {fp['path']}: {fp['description']}"
        for fp in plan.get("files", [])
    )
    user_msg = README_USER.format(
        paper_title=paper.title,
        paper_year=paper.year or "unknown",
        authors=", ".join(paper.authors[:6]),
        project_name=plan.get("project_name", "paper-impl"),
        description=plan.get("description", ""),
        claims=claims_text,
        file_list=file_list,
    )
    raw = await complete_text(README_SYSTEM, user_msg,
                              f"# {paper.title}\n\nImplementation of the paper.\n")
    return _strip_fences(raw) or f"# {paper.title}\n\nSee paper for details.\n"


# ---------------------------------------------------------------------------
# Step 3 — ZIP creation
# ---------------------------------------------------------------------------

def _create_zip(project_name: str, files: dict[str, str]) -> bytes:
    """Pack all generated files into an in-memory ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files.items():
            arc_path = f"{project_name}/{rel_path}"
            zf.writestr(arc_path, content.encode("utf-8", errors="replace"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fallback file content (used when LLM call fails or returns nothing)
# ---------------------------------------------------------------------------

def _fallback_file(path: str, project_name: str, paper: Paper) -> str:
    pkg = project_name.replace("-", "_")
    name = paper.title
    year = paper.year or "unknown"
    authors = ", ".join(paper.authors[:3])

    templates: dict[str, str] = {
        "requirements.txt": (
            "torch>=2.0.0\n"
            "numpy>=1.24.0\n"
            "pyyaml>=6.0\n"
            "tqdm>=4.65.0\n"
            "tensorboard>=2.13.0\n"
        ),
        ".gitignore": (
            "__pycache__/\n*.py[cod]\n*.egg-info/\n.env\n.venv/\n"
            "runs/\ncheckpoints/\n*.pth\n*.pt\ndist/\nbuild/\n"
        ),
        "setup.py": (
            f'from setuptools import setup, find_packages\n\n'
            f'setup(\n'
            f'    name="{project_name}",\n'
            f'    version="0.1.0",\n'
            f'    packages=find_packages("src"),\n'
            f'    package_dir={{"": "src"}},\n'
            f'    python_requires=">=3.10",\n'
            f')\n'
        ),
        "configs/default.yaml": (
            f"# Hyperparameters for {name}\n"
            "model:\n  d_model: 512\n  n_layers: 6\n  dropout: 0.1\n\n"
            "training:\n  lr: 1.0e-4\n  batch_size: 32\n  epochs: 100\n"
            "  warmup_steps: 4000\n\ndata:\n  max_seq_len: 512\n\n"
            "eval:\n  beam_size: 4\n"
        ),
    }
    if path in templates:
        return templates[path]

    if path.endswith("__init__.py"):
        return f'"""Package init for {project_name}."""\n'

    if path.endswith(".sh"):
        return (
            "#!/usr/bin/env bash\nset -e\n\n"
            f"# Reproduce results from: {name} ({year})\n"
            f"echo 'Reproducing {name}'\n"
            "python train.py --config configs/default.yaml\n"
        )

    if path == "README.md":
        return (
            f"# {name}\n\n"
            f"Python implementation of [{name}].\n\n"
            f"**Authors:** {authors}\n\n"
            "## Installation\n```bash\npip install -e .\n```\n\n"
            "## Usage\n```python\n# See train.py for a full example\n```\n"
        )

    # Generic Python file
    module_name = path.replace("/", ".").removesuffix(".py")
    return (
        f'"""\n{module_name}\n\nImplementation of: {name} ({year}).\n"""\n'
        f"from __future__ import annotations\n\n"
        f"import torch\nimport torch.nn as nn\n\n"
        f"# TODO: implement {path} based on paper\n"
    )
