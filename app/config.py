"""Application settings, overridable through GEO_* environment variables or a .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GEO_", env_file=".env", extra="ignore")

    app_name: str = "Geospatial File Measurement API"
    data_dir: Path = Path("data")          # where processed results (JSON) are stored
    max_upload_mb: int = 50                # size of the uploaded file
    max_uncompressed_mb: int = 200         # zip-bomb guard for Shapefile archives
    max_zip_entries: int = 200

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_uncompressed_bytes(self) -> int:
        return self.max_uncompressed_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
