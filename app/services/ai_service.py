"""
AI provider abstraction.

All AI functionality goes through the AIProvider protocol.
No code outside this module may import any provider SDK directly.

Supported providers:
  "anthropic"   → Anthropic SDK (claude-sonnet-4-6, etc.)
  "openai"      → OpenAI SDK (gpt-4o, etc.)
  "openrouter"  → OpenAI-compatible (ai_base_url = https://openrouter.ai/api/v1)
  "ollama"      → OpenAI-compatible (ai_base_url = http://localhost:11434/v1)

Implemented in Phase 6.
"""

from typing import Protocol

from app.models.settings import AppSettings


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


# ---------------------------------------------------------------------------
# Concrete implementations (stubbed — implemented in Phase 6)
# ---------------------------------------------------------------------------

class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def generate(self, system: str, user: str, max_tokens: int) -> str:
        raise NotImplementedError

    async def health_check(self) -> bool:
        raise NotImplementedError


class OpenAIProvider:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url

    async def generate(self, system: str, user: str, max_tokens: int) -> str:
        raise NotImplementedError

    async def health_check(self) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_ai_provider(settings: AppSettings, master_key: bytes) -> AIProvider:
    """
    Read the active provider from AppSettings and return the correct
    AIProvider implementation.

    Args:
        settings: AppSettings ORM row (id=1).
        master_key: From app.state.master_key — used to decrypt the API key.

    Raises:
        ValueError: If ai_provider is not set or is not a recognised value.
    """
    raise NotImplementedError
