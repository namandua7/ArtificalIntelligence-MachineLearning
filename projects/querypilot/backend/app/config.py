from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to backend/ so the MCP server works no matter which cwd a client launches it from.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5434/querypilot"

    secret_key: str = ""

    statement_timeout_ms: int = 10_000
    max_result_rows: int = 1000
    allow_sample_rows: bool = True

    frontend_origin: str = "http://localhost:3001"


settings = Settings()
