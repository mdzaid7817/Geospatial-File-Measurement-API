"""Persistence. One JSON document per processed file, written atomically.

The repository is a tiny interface (save/get) so it can be swapped for SQLite/PostGIS
without touching the service or the routes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.schemas.files import FileRecord

_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex - also blocks path traversal


class JsonFileRepository:
    def __init__(self, base_dir: Path) -> None:
        self._dir = Path(base_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: FileRecord) -> None:
        path = self._dir / f"{record.id}.json"
        tmp = self._dir / f"{record.id}.json.tmp"
        tmp.write_text(record.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)  # atomic: readers never see a half-written file

    def get(self, file_id: str) -> FileRecord | None:
        if not _ID_PATTERN.fullmatch(file_id):
            return None
        path = self._dir / f"{file_id}.json"
        if not path.exists():
            return None
        return FileRecord.model_validate_json(path.read_text(encoding="utf-8"))
