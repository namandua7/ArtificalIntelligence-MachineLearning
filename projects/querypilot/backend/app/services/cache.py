"""In-memory answer cache: an identical question on the same connection is replayed, not recomputed.

A hit skips retrieval, every LLM call and every SQL execution, so a repeated question returns in
milliseconds instead of a minute on a local model. Entries expire after ANSWER_CACHE_TTL_S, and a
connection's entries are dropped whenever something that shapes answers changes (glossary edit,
memory save, re-index) via `bump`. Only successful answers without chat history are cached.
"""

import re
import time
from collections import OrderedDict
from collections import defaultdict
from threading import Lock
from typing import Any

from app.config import settings

MAX_ENTRIES = 64

_lock = Lock()
_entries: "OrderedDict[tuple, tuple[float, list[Any]]]" = OrderedDict()
_epochs: dict[int, int] = defaultdict(int)


def _normalise(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.! ")


def _key(connection_id: int, question: str, flavour: str) -> tuple:
    return (connection_id, _epochs[connection_id], _normalise(question), flavour)


def get(connection_id: int, question: str, flavour: str = "") -> list[Any] | None:
    if settings.answer_cache_ttl_s <= 0:
        return None
    with _lock:
        key = _key(connection_id, question, flavour)
        hit = _entries.get(key)
        if hit is None:
            return None
        stored_at, events = hit
        if time.monotonic() - stored_at > settings.answer_cache_ttl_s:
            del _entries[key]
            return None
        _entries.move_to_end(key)
        return list(events)


def put(connection_id: int, question: str, events: list[Any], flavour: str = "") -> None:
    if settings.answer_cache_ttl_s <= 0:
        return
    with _lock:
        _entries[_key(connection_id, question, flavour)] = (time.monotonic(), list(events))
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def bump(connection_id: int) -> None:
    """Invalidate every cached answer for a connection."""
    with _lock:
        _epochs[connection_id] += 1
        for key in [k for k in _entries if k[0] == connection_id]:
            del _entries[key]


def clear() -> None:
    with _lock:
        _entries.clear()
        _epochs.clear()
