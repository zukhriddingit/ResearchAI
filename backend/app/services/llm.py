from __future__ import annotations

import json
import os
from typing import Any

import httpx


async def complete_json(system: str, user: str, fallback: dict[str, Any]) -> dict[str, Any]:
    text = await complete_text(system, user, json.dumps(fallback))
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else fallback
    except json.JSONDecodeError:
        return fallback


async def complete_text(system: str, user: str, fallback: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
                    "max_tokens": 800,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            content = response.json().get("content", [])
            return content[0].get("text", fallback) if content else fallback
    except Exception:
        return fallback

