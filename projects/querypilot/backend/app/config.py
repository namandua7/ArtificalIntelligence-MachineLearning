from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to backend/ so the MCP server works no matter which cwd a client launches it from.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"  # lowest tier a free key can use

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"
    # Keep models resident between requests (cold-loading a model costs 5-15 s) and cap the context
    # window so a small local model doesn't spend its time on an oversized KV cache.
    ollama_keep_alive: str = "2h"
    # The embedding model is tiny (137M): on CPU it answers in ~0.1-0.7 s and never competes with other GPU
    # apps. Moving a model between GPU and CPU forces a 10-30 s reload, so always use the same setting.
    ollama_embed_on_cpu: bool = True
    ollama_num_ctx: int = 4096

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5434/querypilot"

    secret_key: str = ""

    statement_timeout_ms: int = 10_000
    max_result_rows: int = 1000
    allow_sample_rows: bool = True

    # Latency: identical questions (no chat history) are answered from memory for this long.
    answer_cache_ttl_s: int = 300
    warmup_models_on_start: bool = True

    # Answer with one structured LLM call and only fall back to the tool loop if that SQL fails.
    fast_path: bool = True

    # Self-consistency: "auto" turns it on for fast hosted models (gemini) and off for local ones.
    self_consistency: Literal["auto", "on", "off"] = "off"  # costs extra calls: opt in per question
    consistency_candidates: int = 2

    # Column value profiling at index time (sends distinct values to the LLM like sample rows do,
    # so it also requires allow_sample_rows).
    profile_values: bool = True
    profile_max_columns: int = 250
    profile_max_distinct: int = 40

    # Python analysis sandbox (agent tool run_python).
    sandbox_enabled: bool = True
    sandbox_timeout_s: int = 15
    sandbox_memory_mb: int = 1024

    frontend_origin: str = "http://localhost:3001"


settings = Settings()
