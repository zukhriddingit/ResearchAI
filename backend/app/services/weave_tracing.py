from __future__ import annotations

import os
from typing import Any


_weave = None
_initialized = False


def init_weave() -> bool:
    global _weave, _initialized
    if _initialized:
        return _weave is not None
    _initialized = True
    project = os.getenv("WEAVE_PROJECT")
    if not project:
        return False
    try:
        import weave  # type: ignore

        weave.init(project)
        _weave = weave
        return True
    except Exception:
        _weave = None
        return False


def trace_agent_run(agent_name: str, inputs: dict[str, Any], outputs: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    if not init_weave():
        return
    try:
        _weave.log({"agent": agent_name, "inputs": inputs, "outputs": outputs, "metadata": metadata or {}})
    except Exception:
        return


def log_event(event: Any) -> None:
    if not init_weave():
        return
    try:
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        _weave.log({"event": payload})
    except Exception:
        return

