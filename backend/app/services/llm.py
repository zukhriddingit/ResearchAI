from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from app.services.weave_tracing import init_weave


WANDB_BASE_URL = "https://api.inference.wandb.ai/v1"
DEFAULT_MODEL = "google/gemma-4-31B-it"
DEFAULT_REASONING_MODEL = "deepseek-ai/DeepSeek-V4-Flash"


async def complete_json(
    system: str,
    user: str,
    fallback: dict[str, Any],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> dict[str, Any]:
    text = await complete_text(
        f"{system}\nReturn only valid JSON. Do not wrap it in markdown.",
        user,
        json.dumps(fallback),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else fallback
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return fallback
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else fallback
        except json.JSONDecodeError:
            return fallback


async def complete_text(
    system: str,
    user: str,
    fallback: str,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> str:
    if os.getenv("DEEPPAPER_DISABLE_EXTERNAL") == "1":
        return fallback

    wandb_key = os.getenv("WANDB_API_KEY")
    wandb_project = os.getenv("WANDB_INFERENCE_PROJECT") or os.getenv("WEAVE_PROJECT")
    if wandb_key and wandb_project:
        result = await _complete_with_wandb(
            system,
            user,
            fallback,
            api_key=wandb_key,
            project=wandb_project,
            model=model or os.getenv("WANDB_INFERENCE_MODEL", DEFAULT_MODEL),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if result != fallback:
            return result

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
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            content = response.json().get("content", [])
            return content[0].get("text", fallback) if content else fallback
    except Exception:
        return fallback


async def complete_with_vision(
    system: str,
    user: str,
    images_b64: list[str],
    fallback: str,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> str:
    if not images_b64 or os.getenv("DEEPPAPER_DISABLE_EXTERNAL") == "1":
        return await complete_text(system, user, fallback, model=model, temperature=temperature, max_tokens=max_tokens)

    wandb_key = os.getenv("WANDB_API_KEY")
    wandb_project = os.getenv("WANDB_INFERENCE_PROJECT") or os.getenv("WEAVE_PROJECT")
    if not wandb_key or not wandb_project:
        return fallback

    try:
        from openai import AsyncOpenAI

        init_weave()
        client = AsyncOpenAI(
            base_url=os.getenv("WANDB_INFERENCE_BASE_URL", WANDB_BASE_URL),
            api_key=wandb_key,
            project=wandb_project,
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for image in images_b64[:4]:
            if image:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}})
        response = await client.chat.completions.create(
            model=model or os.getenv("WANDB_INFERENCE_VISION_MODEL", os.getenv("WANDB_INFERENCE_MODEL", DEFAULT_MODEL)),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content_text = response.choices[0].message.content if response.choices else None
        return content_text or fallback
    except Exception:
        return fallback


def reasoning_model() -> str:
    return os.getenv("WANDB_INFERENCE_REASONING_MODEL", DEFAULT_REASONING_MODEL)


async def _complete_with_wandb(
    system: str,
    user: str,
    fallback: str,
    *,
    api_key: str,
    project: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    try:
        from openai import AsyncOpenAI

        init_weave()
        client = AsyncOpenAI(
            base_url=os.getenv("WANDB_INFERENCE_BASE_URL", WANDB_BASE_URL),
            api_key=api_key,
            project=project,
        )
        request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        reasoning_extra = _reasoning_extra_body()
        if reasoning_extra:
            request["extra_body"] = reasoning_extra
        response = await client.chat.completions.create(**request)
        content = response.choices[0].message.content if response.choices else None
        return content or fallback
    except Exception:
        return fallback


def _reasoning_extra_body() -> dict[str, Any] | None:
    value = os.getenv("WANDB_INFERENCE_ENABLE_THINKING")
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        return None
    return {"chat_template_kwargs": {"enable_thinking": normalized in {"1", "true", "yes", "on"}}}
