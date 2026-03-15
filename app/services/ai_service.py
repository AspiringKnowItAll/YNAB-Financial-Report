"""
AI provider abstraction.

All AI functionality goes through the AIProvider protocol.
No code outside this module may import any provider SDK directly.

Supported providers:
  "anthropic"   → Anthropic SDK (claude-sonnet-4-6, etc.)
  "openai"      → OpenAI SDK (gpt-4o, etc.)
  "openrouter"  → OpenAI-compatible (ai_base_url = https://openrouter.ai/api/v1)
  "ollama"      → OpenAI-compatible (ai_base_url = http://localhost:11434/v1)
"""

from typing import Protocol

from app.models.settings import AppSettings
from app.services.encryption import decrypt


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

    async def list_models(self) -> list[str]:
        """Return available model IDs sorted alphabetically."""
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

    async def list_models(self) -> list[str]:
        """Return available model IDs sorted alphabetically."""
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=self._api_key)
        models = await client.models.list(limit=100)
        return sorted(m.id for m in models.data)


# ---------------------------------------------------------------------------
# OpenAI-compatible implementation (OpenAI, OpenRouter, Ollama)
# ---------------------------------------------------------------------------

class OpenAIProvider:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

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

    async def list_models(self) -> list[str]:
        """Return available model IDs sorted alphabetically."""
        response = await self._client().models.list()
        return sorted(m.id for m in response.data)


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

        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

    raise ValueError(
        f"Unknown AI provider: {provider!r}. "
        "Must be one of: anthropic, openai, openrouter, ollama."
    )
