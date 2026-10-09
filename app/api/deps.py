from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.file_service import FileService
from app.services.storage import JsonFileRepository


@lru_cache
def get_file_service() -> FileService:
    settings = get_settings()
    return FileService(JsonFileRepository(settings.data_dir), settings)
