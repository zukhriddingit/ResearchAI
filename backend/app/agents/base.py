from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models import AgentEvent

EventEmitter = Callable[..., AgentEvent]
AgentResult = dict[str, Any]

