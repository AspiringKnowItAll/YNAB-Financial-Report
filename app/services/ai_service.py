"""
AI provider abstraction.

All AI functionality goes through the AIProvider protocol.
No code outside this module may import any provider SDK directly.

Supported providers:
  "anthropic"   → Anthropic SDK (claude-sonnet-4-6, etc.)
  "openai"      → OpenAI SDK (gpt-4o, etc.)
  "openrouter"  → OpenAI-compatible (ai_base_url = https://openrouter.ai/api/v1)
  "ollama"      → OpenAI-compatible (ai_base_url = http://localhost:11434/v1)

Protocol methods:
  generate(system, user, max_tokens)   → batch completion (reports)
  stream(system, user, max_tokens)     → SSE streaming (Life Context Chat)
  health_check()                       → reachability probe
  list_models()                        → available model IDs
  vision(image_bytes, prompt)          → single-image OCR/vision (import_service)
"""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from typing import Protocol, TypedDict

import httpx

from app.models.settings import AppSettings
from app.services.encryption import decrypt

logger = logging.getLogger("app.ai_service")


class ModelInfo(TypedDict):
    id: str
    vision: bool


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class AIProvider(Protocol):
    async def generate(self, system: str, user: str, max_tokens: int) -> str:
        """Generate a completion given system and user prompts."""
        ...

    async def health_check(self) -> bool:
        """Return True if the provider is reachable and the key is valid."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        """Return available model IDs sorted alphabetically."""
        ...

    async def stream(self, system: str, user: str, max_tokens: int) -> AsyncIterator[str]:
        """Stream a completion token-by-token. Yields text chunks as they arrive."""
        ...

    async def vision(self, image_bytes: bytes, prompt: str) -> str:
        """Send a single image with a text prompt and return the response text."""
        ...


# ---------------------------------------------------------------------------
# Anthropic implementation
# ---------------------------------------------------------------------------

class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def generate(self, system: str, user: str, max_tokens: int) -> str:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        response = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    async def health_check(self) -> bool:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self._api_key)
            await client.messages.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    async def list_models(self) -> list[ModelInfo]:
        """Return available model IDs sorted alphabetically."""
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        models = await client.models.list(limit=100)
        # All current Anthropic models support vision
        return [{"id": m.id, "vision": True} for m in sorted(models.data, key=lambda m: m.id)]

    async def stream(self, system: str, user: str, max_tokens: int) -> AsyncIterator[str]:
        """Stream a completion token-by-token using Anthropic's streaming API."""
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        async with client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream_ctx:
            async for text in stream_ctx.text_stream:
                yield text

    async def vision(self, image_bytes: bytes, prompt: str) -> str:
        """Send a single image with a text prompt and return the response text."""
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        response = await client.messages.create(
            model=self._model,
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        if not response.content:
            return ""
        return response.content[0].text


# ---------------------------------------------------------------------------
# OpenAI-compatible implementation (OpenAI, OpenRouter, Ollama)
# ---------------------------------------------------------------------------

class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._provider_name = provider_name

    def _client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self._api_key or "ollama", base_url=self._base_url)

    async def generate(self, system: str, user: str, max_tokens: int) -> str:
        response = await self._client().chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    async def health_check(self) -> bool:
        try:
            await self._client().chat.completions.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    async def list_models(self) -> list[ModelInfo]:
        """Return available model IDs sorted alphabetically."""
        if self._provider_name == "openrouter":
            return await self._list_models_openrouter()
        if self._provider_name == "ollama":
            return await self._list_models_ollama()
        # OpenAI: no capability metadata available, use name heuristics
        response = await self._client().models.list()
        _VISION_SUBSTRINGS = (
            "gpt-4o", "gpt-4-turbo", "gpt-4-vision", "o1", "o3", "o4-mini",
        )
        ids = sorted(m.id for m in response.data)
        return [
            {"id": mid, "vision": any(s in mid for s in _VISION_SUBSTRINGS)}
            for mid in ids
        ]

    async def _list_models_openrouter(self) -> list[ModelInfo]:
        """Fetch models from OpenRouter with architecture.modality metadata."""
        base = (self._base_url or "https://openrouter.ai/api/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{base}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        result: list[ModelInfo] = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            if not model_id:
                continue
            modality = m.get("architecture", {}).get("modality", "")
            result.append({"id": model_id, "vision": "image" in modality})
        return sorted(result, key=lambda x: x["id"])

    async def _list_models_ollama(self) -> list[ModelInfo]:
        """Fetch models from Ollama with per-model capability checks."""
        # Derive the base Ollama host URL (strip /v1 suffix)
        show_base = (self._base_url or "http://localhost:11434/v1").rstrip("/")
        if show_base.endswith("/v1"):
            show_base = show_base[:-3]

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Get full model list from native /api/tags endpoint
            tags_resp = await client.get(f"{show_base}/api/tags")
            tags_resp.raise_for_status()
            models = tags_resp.json().get("models", [])

            # 2. Query /api/show for each model in parallel (max 10 concurrent)
            sem = asyncio.Semaphore(10)

            async def get_vision(model_name: str) -> bool:
                async with sem:
                    try:
                        r = await client.post(
                            f"{show_base}/api/show",
                            json={"name": model_name},
                            timeout=5.0,
                        )
                        r.raise_for_status()
                        return "vision" in r.json().get("capabilities", [])
                    except Exception as exc:
                        logger.debug("Ollama /api/show probe failed for %s: %s", model_name, exc)
                        return False

            names = [m.get("name") or m.get("model", "") for m in models]
            names = [n for n in names if n]
            vision_flags = await asyncio.gather(*[get_vision(n) for n in names])

        result: list[ModelInfo] = [
            {"id": name, "vision": bool(vis)}
            for name, vis in zip(names, vision_flags)
        ]
        return sorted(result, key=lambda x: x["id"])

    async def stream(self, system: str, user: str, max_tokens: int) -> AsyncIterator[str]:
        """Stream a completion token-by-token using the OpenAI streaming API."""
        stream = await self._client().chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def vision(self, image_bytes: bytes, prompt: str) -> str:
        """Send a single image with a text prompt and return the response text."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        response = await self._client().chat.completions.create(
            model=self._model,
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_ai_provider_from_params(
    provider_name: str,
    api_key: str = "",
    base_url: str | None = None,
) -> AIProvider:
    """
    Build an AIProvider directly from plaintext parameters (no DB / encryption).

    Used by the Settings UI test button so the user can test connectivity
    before saving settings.
    """
    model = "ping"  # Placeholder — only used for health_check, not list_models

    if provider_name == "anthropic":
        if not api_key:
            raise ValueError("Anthropic API key is required.")
        return AnthropicProvider(api_key=api_key, model=model)

    if provider_name in ("openai", "openrouter", "ollama"):
        if not api_key and provider_name != "ollama":
            raise ValueError(f"{provider_name.capitalize()} API key is required.")
        if provider_name in ("openrouter", "ollama") and not base_url:
            raise ValueError(f"{provider_name.capitalize()} base URL is required.")
        return OpenAIProvider(
            api_key=api_key,
            model=model,
            base_url=base_url if provider_name in ("openrouter", "ollama") else None,
            provider_name=provider_name,
        )

    raise ValueError(f"Unknown AI provider: {provider_name!r}.")


def get_ai_provider(settings: AppSettings, master_key: bytes) -> AIProvider:
    """
    Read the active provider from AppSettings and return the correct
    AIProvider implementation.

    Args:
        settings: AppSettings ORM row (id=1).
        master_key: From app.state.master_key — used to decrypt the API key.

    Raises:
        ValueError: If ai_provider is not set or is not a recognised value,
                    or if a required API key is missing.
    """
    provider = settings.ai_provider
    model = settings.ai_model

    if not provider:
        raise ValueError("AI provider is not configured. Set it in Settings.")

    if not model:
        # Provide sensible defaults per provider
        _defaults = {
            "anthropic": "claude-sonnet-4-6",
            "openai": "gpt-4o",
            "openrouter": "openai/gpt-4o",
            "ollama": "llama3",
        }
        model = _defaults.get(provider, "gpt-4o")

    if provider == "anthropic":
        if not settings.ai_api_key_enc:
            raise ValueError("Anthropic API key is not configured.")
        api_key = decrypt(settings.ai_api_key_enc, master_key)
        return AnthropicProvider(api_key=api_key, model=model)

    if provider in ("openai", "openrouter", "ollama"):
        # Ollama does not require an API key
        api_key = ""
        if settings.ai_api_key_enc:
            api_key = decrypt(settings.ai_api_key_enc, master_key)
        elif provider != "ollama":
            raise ValueError(f"{provider.capitalize()} API key is not configured.")

        base_url: str | None = None
        if provider in ("openrouter", "ollama"):
            if not settings.ai_base_url:
                raise ValueError(f"{provider.capitalize()} base URL is not configured.")
            base_url = settings.ai_base_url

        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url, provider_name=provider)

    raise ValueError(
        f"Unknown AI provider: {provider!r}. "
        "Must be one of: anthropic, openai, openrouter, ollama."
    )
