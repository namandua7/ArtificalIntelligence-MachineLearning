from typing import Literal

import ollama

from app.config import settings

_client: ollama.Client | None = None


def _get_client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(host=settings.ollama_base_url)
    return _client


def embed_texts(texts: list[str], input_type: Literal["document", "query"]) -> list[list[float]]:
    """Embed a batch of texts with a local Ollama model. input_type is unused (kept for
    call-site symmetry with the previous Voyage-backed implementation; Ollama embedding
    models don't distinguish query vs. document inputs the way Voyage does)."""
    if not texts:
        return []
    result = _get_client().embed(model=settings.ollama_embed_model, input=texts)
    return result.embeddings


def embed_query(text: str) -> list[float]:
    return embed_texts([text], input_type="query")[0]
