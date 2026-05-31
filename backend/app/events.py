from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.models import AgentEvent
from app.store import store


def emit(
    session_id: str,
    event_type: str,
    message: str,
    *,
    agent: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentEvent:
    event = AgentEvent(
        session_id=session_id,
        type=event_type,
        agent=agent,
        status=status,
        message=message,
        payload=payload or {},
    )
    session = store.get_session(session_id)
    session.events.append(event)
    return event


async def stream_events(session_id: str) -> AsyncIterator[str]:
    cursor = 0
    while True:
        session = store.get_session(session_id)
        while cursor < len(session.events):
            event = session.events[cursor]
            cursor += 1
            yield f"data: {json.dumps(event.model_dump())}\n\n"
        await asyncio.sleep(0.7)

