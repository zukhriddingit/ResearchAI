from __future__ import annotations

import json
import os
import re
from typing import Any

from app.services.weave_tracing import op as weave_op


@weave_op
async def complete_json(system: str, user: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """Call the configured LLM and parse the response as JSON. Returns fallback on any failure."""
    text = await complete_text(system, user, json.dumps(fallback))
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
    Route to the configured LLM provider.
    Set LLM_PROVIDER env var: groq (default) | ollama | anthropic
    """
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        return await _groq(system, user, fallback)
    if provider == "ollama":
        return await _ollama(system, user, fallback)
    if provider == "anthropic":
        return await _anthropic(system, user, fallback)
    return fallback


@weave_op
async def complete_with_vision(
    system: str,
    user: str,
    images_b64: list[str],
    fallback: str,
) -> str:
    """
    Call a vision-capable LLM with text + images (base64 PNG strings).

    Uses Groq llama-3.2-11b-vision-preview by default.
    Falls back to text-only if no vision key or image list is empty.
    """
    if not images_b64:
        return await complete_text(system, user, fallback)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback

    try:
        from openai import AsyncOpenAI  # Groq is OpenAI-compatible; Weave auto-patches this
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        content: list[dict] = [{"type": "text", "text": user}]
        for img_b64 in images_b64[:4]:  # cap at 4 images per call
            if img_b64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                })

        resp = await client.chat.completions.create(
            model=os.getenv("GROQ_VISION_MODEL", "llama-3.2-11b-vision-preview"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            max_tokens=900,
            temperature=0.2,
        )
        return resp.choices[0].message.content or fallback
    except Exception:
        # Vision call failed — fall back to text-only analysis
        return await complete_text(system, user, fallback)


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _groq(system: str, user: str, fallback: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        resp = await client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=900,
            temperature=0.2,
        )
        return resp.choices[0].message.content or fallback
    except Exception:
        return fallback


async def _ollama(system: str, user: str, fallback: str) -> str:
    import httpx
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 900},
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
    except Exception:
        return fallback


async def _anthropic(system: str, user: str, fallback: str) -> str:
    import httpx
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
                      "max_tokens": 900, "system": system,
                      "messages": [{"role": "user", "content": user}]},
            )
            response.raise_for_status()
            content = response.json().get("content", [])
            return content[0].get("text", fallback) if content else fallback
    except Exception:
        return fallback
