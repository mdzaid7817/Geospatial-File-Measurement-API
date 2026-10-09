"""Format-neutral parser output. Stdlib only, so every parser can be tested in isolation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class RawFeature:
    index: int                              # 0-based position in the file
    geometry: dict[str, Any] | None         # 2D GeoJSON-style mapping, or None if unusable
    properties: dict[str, Any] = field(default_factory=dict)
    problem: str | None = None              # why geometry is None / questionable


@dataclass
class ParsedFile:
    features: list[RawFeature]
    crs_definition: str | None              # "EPSG:4326", WKT, ... or None if the file has none
    warnings: list[str] = field(default_factory=list)


class FileParser(Protocol):
    def parse(self, path: Path) -> ParsedFile: ...
