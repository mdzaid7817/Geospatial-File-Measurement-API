"""Shapefile (zipped) parser built on pyshp (pure Python, no GDAL needed)."""
from __future__ import annotations

import codecs
import tempfile
from pathlib import Path
from typing import Any

import shapefile  # pyshp

from app.core.exceptions import InvalidFileError
from app.parsers.archive import extract_shapefile
from app.parsers.base import ParsedFile, RawFeature


def _strip_to_2d(coords: Any) -> Any:
    """Drop Z/M values: measurements are planar, and shapely wants 2D/3D only."""
    if len(coords) and isinstance(coords[0], (int, float)):
        return [coords[0], coords[1]]
    return [_strip_to_2d(c) for c in coords]


def _detect_encoding(cpg: Path) -> str:
    """Honour the .cpg sidecar (e.g. 'UTF-8' or '1252'); default to UTF-8."""
    if cpg.exists():
        label = cpg.read_text(errors="ignore").strip()
        for candidate in (label, f"cp{label}"):
            try:
                return codecs.lookup(candidate).name
            except LookupError:
                continue
    return "utf-8"


def _to_raw(index: int, shape_record: Any) -> RawFeature:
    props = shape_record.record.as_dict()
    shp = shape_record.shape
    if shp.shapeType == shapefile.NULL:
        return RawFeature(index, None, props, "Null shape: feature has no geometry")
    try:
        geo = shp.__geo_interface__
        geometry = {"type": geo["type"], "coordinates": _strip_to_2d(geo["coordinates"])}
    except Exception as exc:  # noqa: BLE001 - a single odd shape (e.g. MultiPatch) must not fail the file
        return RawFeature(
            index, None, props, f"Unsupported or malformed shape (shapeType={shp.shapeType}): {exc}"
        )
    return RawFeature(index, geometry, props)


class ShapefileParser:
    def __init__(self, max_entries: int, max_uncompressed_bytes: int) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_uncompressed_bytes

    def parse(self, path: Path) -> ParsedFile:
        with tempfile.TemporaryDirectory(prefix="shp_") as tmp:
            shp_path, warnings = extract_shapefile(
                path, Path(tmp),
                max_entries=self._max_entries, max_uncompressed_bytes=self._max_bytes,
            )
            prj = shp_path.with_suffix(".prj")
            crs_definition = prj.read_text(errors="ignore").strip() if prj.exists() else None
            encoding = _detect_encoding(shp_path.with_suffix(".cpg"))

            features: list[RawFeature] = []
            try:
                with shapefile.Reader(str(shp_path), encoding=encoding, encodingErrors="replace") as sf:
                    for index, sr in enumerate(sf.iterShapeRecords()):
                        features.append(_to_raw(index, sr))
            except Exception as exc:  # noqa: BLE001 - corrupt binary data raises many exception types
                raise InvalidFileError(f"Could not read shapefile: {exc}") from exc

        if not features:
            raise InvalidFileError("Shapefile contains no features")
        return ParsedFile(features=features, crs_definition=crs_definition or None, warnings=warnings)
