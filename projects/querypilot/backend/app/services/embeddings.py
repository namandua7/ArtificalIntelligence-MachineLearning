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
        model=settings.ollama_embed_model, input=[prefix + t for t in texts]
    )
    return [list(v) for v in response.embeddings]


def embed_query(text: str) -> list[float]:
    return embed_texts([text], input_type="query")[0]
