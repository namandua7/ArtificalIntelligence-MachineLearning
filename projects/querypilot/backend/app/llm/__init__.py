from app.config import settings
from app.llm.base import LLMError, LLMProvider

_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        if settings.llm_provider == "gemini":
            from app.llm.gemini import GeminiProvider

            _provider = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
        else:
            from app.llm.ollama_provider import OllamaProvider

            _provider = OllamaProvider(settings.ollama_base_url, settings.ollama_chat_model)
    return _provider


def describe_llm() -> dict[str, str | bool]:
    """For the UI header; never raises (a missing key should not break page loads)."""
    if settings.llm_provider == "gemini":
        return {
            "provider": "gemini",
            "model": settings.gemini_model,
            "configured": bool(settings.gemini_api_key),
        }
    return {"provider": "ollama", "model": settings.ollama_chat_model, "configured": True}


__all__ = ["LLMError", "LLMProvider", "get_llm", "describe_llm"]
