"""
Конфигурация приложения через Pydantic Settings.
Читает переменные из .env и окружения.
"""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Supabase
    supabase_url:         str = ""
    supabase_anon_key:    str = ""
    supabase_service_key: str = ""
    database_url:         str = ""   # postgresql+asyncpg://...

    # AI / Search
    anthropic_api_key: str = ""
    tavily_api_key:    str = ""

    # App
    app_env:        str = "development"
    app_secret_key: str = "change-me"

    # Storage bucket names
    storage_bucket_mk:       str = "mk-files"
    storage_bucket_drawings: str = "drawings"
    storage_bucket_quotes:   str = "quote-attachments"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def db_configured(self) -> bool:
        return bool(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
