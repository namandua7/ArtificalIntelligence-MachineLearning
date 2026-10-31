from app.config import settings
from app.llm.base import LLMError, LLMProvider

_providers: dict[tuple[str, str], LLMProvider] = {}


def get_llm(model: str | None = None) -> LLMProvider:
    """The configured provider; `model` overrides the model name (used by evals to compare models)."""
    name = settings.llm_provider
    default = settings.gemini_model if name == "gemini" else settings.ollama_chat_model
    model = model or default
    key = (name, model)
    provider = _providers.get(key)
    if provider is None:
        if name == "gemini":
            from app.llm.gemini import GeminiProvider

            provider = GeminiProvider(settings.gemini_api_key, model)
        else:
            from app.llm.ollama_provider import OllamaProvider

            provider = OllamaProvider(settings.ollama_base_url, model)
        _providers[key] = provider
    return provider


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
