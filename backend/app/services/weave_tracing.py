from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any


_weave = None
_initialized = False


def init_weave() -> bool:
    global _weave, _initialized
    if _initialized:
        return _weave is not None
    if os.getenv("DEEPPAPER_DISABLE_EXTERNAL") == "1":
        _initialized = True
        return False
    _initialized = True
    project = os.getenv("WEAVE_PROJECT") or os.getenv("WANDB_INFERENCE_PROJECT")
    api_key = os.getenv("WANDB_API_KEY")
    if not project or not api_key:
        return False
    try:
        import weave  # type: ignore

        weave.init(project)
        _weave = weave
        return True
    except Exception:
        _weave = None
        return False


def op(fn: Callable) -> Callable:
    """Wrap a function as a Weave op when the package is available."""
    try:
        import weave  # type: ignore

        return weave.op()(fn)
    except Exception:
        return fn


async def traced_agent_call(
    agent_name: str,
    inputs: dict[str, Any],
    call: Callable[[], Awaitable[Any]],
) -> Any:
    """Run an async agent call as a Weave op when Weave is configured."""
    output = await call()
    trace_agent_run(agent_name, inputs, _safe_dump(output))
    return output


def trace_agent_run(agent_name: str, inputs: dict[str, Any], outputs: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
    if not init_weave():
        return
    try:
        @(_weave.op(name=f"agent.{agent_name.lower()}.summary"))
        def _log_agent_run() -> dict[str, Any]:
            return {"agent": agent_name, "inputs": inputs, "outputs": outputs, "metadata": metadata or {}}

        _log_agent_run()
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


def _safe_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(key): _safe_dump_item(item) for key, item in value.items()}
    return {"output": _safe_dump_item(value)}


def _safe_dump_item(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_safe_dump_item(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_dump_item(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
