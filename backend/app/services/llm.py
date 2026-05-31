from __future__ import annotations

import json
import os
import re
from typing import Any

from app.services.weave_tracing import op as weave_op


@weave_op
async def complete_json(system: str, user: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """
    Call the configured LLM and parse the response as JSON.

    Strips markdown code fences before parsing. Returns `fallback` on any
    failure — missing API key, network error, or malformed JSON.
    """
    text = await complete_text(system, user, json.dumps(fallback))
    # Strip ```json ... ``` fences that models sometimes add
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else fallback
    except json.JSONDecodeError:
        return fallback


@weave_op
async def complete_text(system: str, user: str, fallback: str) -> str:
    """
    Call the configured LLM provider and return the raw text response.

    Provider priority (set LLM_PROVIDER env var):
      groq      — Groq free tier via OpenAI-compatible API (default)
      ollama    — Local Ollama instance, zero cost
      anthropic — Anthropic Claude via raw HTTP

    Returns `fallback` when no API key is set or any call fails.
    """
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        return await _groq(system, user, fallback)
    if provider == "ollama":
        return await _ollama(system, user, fallback)
    if provider == "anthropic":
        return await _anthropic(system, user, fallback)
    return fallback


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _groq(system: str, user: str, fallback: str) -> str:
    """Groq LPU inference — free tier at console.groq.com."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback
    try:
        from openai import AsyncOpenAI  # Weave auto-patches AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        resp = await client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=900,
            temperature=0.2,
        )
        return resp.choices[0].message.content or fallback
    except Exception:
        return fallback


async def _ollama(system: str, user: str, fallback: str) -> str:
    """Ollama local inference — completely free, no network needed."""
    import httpx
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 900},
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
    except Exception:
        return fallback


async def _anthropic(system: str, user: str, fallback: str) -> str:
    """Anthropic Claude via raw HTTP — kept for compatibility."""
    import httpx
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
                    "max_tokens": 900,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            content = response.json().get("content", [])
            return content[0].get("text", fallback) if content else fallback
    except Exception:
        return fallback
