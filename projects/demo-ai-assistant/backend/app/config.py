from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/blogdb"

    similarity_threshold: float = 0.5

    frontend_origin: str = "http://localhost:3000"


settings = Settings()
