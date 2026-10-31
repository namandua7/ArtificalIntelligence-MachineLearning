from functools import lru_cache
from typing import Literal

import ollama

from app.config import settings

# nomic-embed-text is trained with task prefixes; using them noticeably improves retrieval.
_PREFIX = {"document": "search_document: ", "query": "search_query: "}

_client: ollama.Client | None = None


def _get_client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(host=settings.ollama_base_url)
    return _client


def embed_texts(texts: list[str], input_type: Literal["document", "query"]) -> list[list[float]]:
    if not texts:
        return []
    prefix = _PREFIX[input_type]
    response = _get_client().embed(
        model=settings.ollama_embed_model,
        input=[prefix + t for t in texts],
        keep_alive=settings.ollama_keep_alive,
        options={"num_gpu": 0} if settings.ollama_embed_on_cpu else None,
    )
    return [list(v) for v in response.embeddings]


@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    return tuple(embed_texts([text], input_type="query")[0])


def embed_query(text: str) -> list[float]:
    """Question embeddings are cached: repeated and retried questions skip the model call entirely."""
    return list(_embed_query_cached(text.strip()))
