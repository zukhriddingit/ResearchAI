from __future__ import annotations

import os
from typing import Any, Callable

_weave = None
_initialized = False


def init_weave() -> bool:
    """
    Initialize Weave for the current process.

    Call once at app startup. Reads WEAVE_PROJECT and WANDB_API_KEY from env.
    Returns True if Weave is live and traces will be pushed to the portal.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _weave, _initialized
    if _initialized:
        return _weave is not None
    _initialized = True

    project = os.getenv("WEAVE_PROJECT")
    if not project:
        return False

    try:
        import wandb  # noqa: F401  ensure wandb is importable first
        import weave

        weave.init(project)
        _weave = weave
        return True
    except Exception as exc:
        print(f"[weave] init failed — traces will not be pushed ({exc})")
        _weave = None
        return False


def op(fn: Callable) -> Callable:
    """
    Decorator: wrap a sync or async function as a Weave op.

    Applied at import-time. If Weave is not installed the function is returned
    unchanged. If Weave IS installed but init_weave() hasn't been called yet,
    the op is registered and will start tracing as soon as init_weave() runs.

    Usage:
        from app.services.weave_tracing import op as weave_op

        @weave_op
        async def run_my_agent(...):
            ...
    """
    try:
        import weave  # noqa: F401
        return weave.op()(fn)
    except ImportError:
        return fn
    except Exception:
        return fn


def trace_agent_run(
    agent_name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Legacy helper kept for compatibility with existing main.py calls."""
    if not init_weave() or _weave is None:
        return
    try:
        _weave.log({"agent": agent_name, "inputs": inputs, "outputs": outputs, "metadata": metadata or {}})
    except Exception:
        pass


def log_event(event: Any) -> None:
    """Log an AgentEvent to Weave. Legacy helper kept for main.py compatibility."""
    if not init_weave() or _weave is None:
        return
    try:
        payload = event.model_dump() if hasattr(event, "model_dump") else event
        _weave.log({"event": payload})
    except Exception:
        pass
